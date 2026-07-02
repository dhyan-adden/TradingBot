#!/usr/bin/env node
import "dotenv/config";

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:http";

const apiKey = process.env.ZERODHA_API_KEY;
const apiSecret = process.env.ZERODHA_API_SECRET;
const args = process.argv.slice(2);
const listenMode = args.includes("--listen");
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

if (listenMode) {
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
}
