#!/usr/bin/env node
import "dotenv/config";

import { createHash, createHmac } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:http";

const apiKey = process.env.ZERODHA_API_KEY;
const apiSecret = process.env.ZERODHA_API_SECRET;
const args = process.argv.slice(2);
const listenMode = args.includes("--listen");
const autoMode = args.includes("--auto");
const requestToken = args.find((arg) => !arg.startsWith("--")) ?? process.env.ZERODHA_REQUEST_TOKEN;
const loginUrl = `https://kite.zerodha.com/connect/login?v=3&api_key=${encodeURIComponent(apiKey ?? "")}`;

if (!apiKey) {
  throw new Error("Missing ZERODHA_API_KEY in .env");
}

if (!apiSecret) {
  throw new Error("Missing ZERODHA_API_SECRET in .env");
}

const kiteApiKey = apiKey;
const kiteApiSecret = apiSecret;

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing ${name} in .env (needed for --auto login)`);
  }
  return value;
}

// RFC 4648 base32 decode (TOTP secrets are base32).
function base32Decode(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = secret.replace(/=+$/, "").toUpperCase().replace(/\s+/g, "");
  let bits = 0;
  let value = 0;
  const out: number[] = [];
  for (const char of clean) {
    const idx = alphabet.indexOf(char);
    if (idx === -1) continue;
    value = (value << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(out);
}

// RFC 6238 TOTP: SHA1, 6 digits, 30s step - what Zerodha's authenticator uses.
function totp(secretBase32: string, forTimeMs: number = Date.now()): string {
  const counter = Math.floor(forTimeMs / 1000 / 30);
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const hmac = createHmac("sha1", base32Decode(secretBase32)).update(buf).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const code =
    ((hmac[offset] & 0x7f) << 24) |
    ((hmac[offset + 1] & 0xff) << 16) |
    ((hmac[offset + 2] & 0xff) << 8) |
    (hmac[offset + 3] & 0xff);
  return (code % 1_000_000).toString().padStart(6, "0");
}

function assertTotpImpl() {
  // RFC 6238 Appendix B vector: ASCII "12345678901234567890" at t=59s -> 287082.
  const got = totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59_000);
  if (got !== "287082") {
    throw new Error(`TOTP self-check failed (got ${got}, expected 287082); refusing to send a wrong code`);
  }
}

function applySetCookies(jar: Map<string, string>, response: Response) {
  for (const cookie of response.headers.getSetCookie()) {
    const pair = cookie.split(";")[0];
    const eq = pair.indexOf("=");
    if (eq === -1) continue;
    jar.set(pair.slice(0, eq).trim(), pair.slice(eq + 1).trim());
  }
}

function cookieHeader(jar: Map<string, string>): string {
  return [...jar].map(([name, value]) => `${name}=${value}`).join("; ");
}

// Headless Kite login: password -> TOTP 2FA -> connect/login redirect -> request_token.
async function autoLogin(): Promise<string> {
  const userId = required("ZERODHA_USER_ID");
  const password = required("ZERODHA_PASSWORD");
  const totpSecret = required("ZERODHA_TOTP_SECRET");
  assertTotpImpl();

  const jar = new Map<string, string>();

  const loginResponse = await fetch("https://kite.zerodha.com/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ user_id: userId, password })
  });
  applySetCookies(jar, loginResponse);
  const loginData = await loginResponse.json();
  if (loginData?.status !== "success" || !loginData?.data?.request_id) {
    throw new Error(`Password login failed: ${JSON.stringify(loginData)}`);
  }

  const twofaResponse = await fetch("https://kite.zerodha.com/api/twofa", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Cookie: cookieHeader(jar)
    },
    body: new URLSearchParams({
      user_id: userId,
      request_id: loginData.data.request_id,
      twofa_value: totp(totpSecret),
      twofa_type: "totp"
    })
  });
  applySetCookies(jar, twofaResponse);
  const twofaData = await twofaResponse.json();
  if (twofaData?.status !== "success") {
    throw new Error(`TOTP 2FA failed: ${JSON.stringify(twofaData)}`);
  }

  let url = `https://kite.zerodha.com/connect/login?v=3&api_key=${encodeURIComponent(kiteApiKey)}`;
  for (let hop = 0; hop < 10; hop++) {
    const response = await fetch(url, {
      method: "GET",
      redirect: "manual",
      headers: { Cookie: cookieHeader(jar) }
    });
    applySetCookies(jar, response);
    if (response.status < 300 || response.status >= 400) {
      throw new Error(`connect/login expected a redirect but got ${response.status}`);
    }
    const location = response.headers.get("location");
    if (!location) {
      throw new Error("connect/login redirect had no Location header");
    }
    const next = new URL(location, url);
    const token = next.searchParams.get("request_token");
    if (token) return token;
    url = next.toString();
  }
  throw new Error("Did not receive request_token after following connect/login redirects");
}

async function exchangeRequestToken(token: string) {
  const checksum = createHash("sha256")
    .update(`${kiteApiKey}${token}${kiteApiSecret}`)
    .digest("hex");

  const body = new URLSearchParams({
    api_key: kiteApiKey,
    request_token: token,
    checksum
  });

  const response = await fetch("https://api.kite.trade/session/token", {
    method: "POST",
    headers: {
      "X-Kite-Version": "3",
      "Content-Type": "application/x-www-form-urlencoded"
    },
    body
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    throw new Error(`Token exchange failed ${response.status}: ${JSON.stringify(data)}`);
  }

  const accessToken = data?.data?.access_token;
  if (!accessToken) {
    throw new Error(`Token exchange succeeded but no access_token was returned: ${JSON.stringify(data)}`);
  }

  return accessToken as string;
}

async function updateEnvAccessToken(accessToken: string) {
  const envPath = ".env";
  let env = "";

  try {
    env = await readFile(envPath, "utf8");
  } catch {
    env = "";
  }

  const nextLine = `ZERODHA_ACCESS_TOKEN=${accessToken}`;
  const nextEnv = env.match(/^ZERODHA_ACCESS_TOKEN=.*$/m)
    ? env.replace(/^ZERODHA_ACCESS_TOKEN=.*$/m, nextLine)
    : `${env.trimEnd()}\n${nextLine}\n`;

  await writeFile(envPath, nextEnv);
}

async function finish(token: string) {
  const accessToken = await exchangeRequestToken(token);
  await updateEnvAccessToken(accessToken);
  console.log("Updated .env with the new ZERODHA_ACCESS_TOKEN.");
}

if (autoMode) {
  await finish(await autoLogin());
} else if (listenMode) {
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? "/", "http://localhost:8080");
      const token = url.searchParams.get("request_token");
      const status = url.searchParams.get("status");

      if (url.pathname !== "/login" || !token || status !== "success") {
        res.writeHead(400, { "Content-Type": "text/plain" });
        res.end("Missing successful Zerodha request_token.");
        return;
      }

      await finish(token);
      res.writeHead(200, { "Content-Type": "text/plain" });
      res.end("Zerodha access token saved. You can close this tab.");
      server.close();
    } catch (error) {
      res.writeHead(500, { "Content-Type": "text/plain" });
      res.end(error instanceof Error ? error.message : String(error));
      server.close();
    }
  });

  server.listen(8080, "127.0.0.1", () => {
    console.log("Listening on http://localhost:8080/login");
    console.log("Open this URL and complete Zerodha login:");
    console.log(loginUrl);
  });
} else if (requestToken) {
  await finish(requestToken);
} else {
  console.log("Open this URL, login, then copy request_token from the redirect URL:");
  console.log(loginUrl);
  console.log("");
  console.log("Then run:");
  console.log("npm run auth:zerodha -- <request_token>");
  console.log("");
  console.log("Or use callback mode if your Zerodha redirect URL is http://localhost:8080/login:");
  console.log("npm run auth:zerodha -- --listen");
  console.log("");
  console.log("Or fully headless (needs ZERODHA_USER_ID, ZERODHA_PASSWORD, ZERODHA_TOTP_SECRET in .env):");
  console.log("npm run auth:zerodha -- --auto");
}
