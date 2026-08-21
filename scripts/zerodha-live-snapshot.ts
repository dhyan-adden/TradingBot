#!/usr/bin/env node
import { mkdir, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const KITE_BASE_URL = "https://api.kite.trade";

type QueryValue = string | number | boolean | undefined;

function requireCredentials() {
  const apiKey = process.env.ZERODHA_API_KEY;
  const accessToken = process.env.ZERODHA_ACCESS_TOKEN;
  if (!apiKey || !accessToken) {
    throw new Error("missing ZERODHA_API_KEY or ZERODHA_ACCESS_TOKEN");
  }
  return { apiKey, accessToken };
}

function buildUrl(path: string, query?: Record<string, QueryValue | QueryValue[]>) {
  const url = new URL(path, KITE_BASE_URL);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined) url.searchParams.append(key, String(item));
      }
      continue;
    }
    url.searchParams.set(key, String(value));
  }
  return url;
}

async function kiteRequest<T>(
  path: string,
  options: { query?: Record<string, QueryValue | QueryValue[]> } = {}
): Promise<T> {
  const { apiKey, accessToken } = requireCredentials();
  const headers = new Headers({
    Authorization: `token ${apiKey}:${accessToken}`,
    "X-Kite-Version": "3",
  });
  const response = await fetch(buildUrl(path, options.query), { method: "GET", headers });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(`Kite API ${response.status}`);
  }
  return (data?.data ?? data) as T;
}

export interface Holding {
  tradingsymbol?: string;
  exchange?: string;
  quantity?: number;
}

export interface Position {
  tradingsymbol?: string;
  exchange?: string;
  quantity?: number;
}

export interface Order {
  tradingsymbol?: string;
  exchange?: string;
  transaction_type?: string;
  quantity?: number;
  status?: string;
}

export interface EquityMargins {
  available?: {
    cash?: number;
    intraday?: number;
    collateral?: number;
    adhoc_margin?: number;
  };
  enabled?: boolean;
  net?: number;
}

const OPEN_STATUSES = new Set(["OPEN", "PENDING", "TRIGGER PENDING"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function normalizedQuantity(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? Math.floor(n) : 0;
}

function normalizedSymbol(value: unknown): string {
  return String(value ?? "").trim().toUpperCase();
}

export function normalizePositionsResponse(value: unknown): Position[] {
  if (Array.isArray(value)) return value as Position[];
  if (isRecord(value)) {
    const net = value.net;
    const day = value.day;
    if ((net === undefined || Array.isArray(net)) && (day === undefined || Array.isArray(day))) {
      return [...((net ?? []) as Position[]), ...((day ?? []) as Position[])];
    }
  }
  throw new Error("unexpected positions response shape");
}

export function buildHoldingsMap(holdings: Holding[], positionsResponse: unknown): Record<string, number> {
  const holdingsMap: Record<string, number> = {};
  for (const h of holdings ?? []) {
    if (h.exchange !== "NSE") continue;
    const sym = normalizedSymbol(h.tradingsymbol);
    if (!sym) continue;
    const qty = normalizedQuantity(h.quantity);
    if (qty <= 0) continue;
    holdingsMap[sym] = Math.max(holdingsMap[sym] ?? 0, qty);
  }
  // Merge positions conservatively: max per symbol, never sum (sum could
  // authorize an oversell when a symbol appears in multiple broker views).
  for (const p of normalizePositionsResponse(positionsResponse)) {
    if (p.exchange !== "NSE") continue;
    const sym = normalizedSymbol(p.tradingsymbol);
    if (!sym) continue;
    const qty = normalizedQuantity(p.quantity);
    if (qty <= 0) continue;
    holdingsMap[sym] = Math.max(holdingsMap[sym] ?? 0, qty);
  }
  return holdingsMap;
}

export function normalizeOpenOrders(orders: Order[]): Array<{ symbol: string; side: string; quantity: number; status: string }> {
  const openOrders: Array<{ symbol: string; side: string; quantity: number; status: string }> = [];
  for (const o of orders ?? []) {
    if (o.exchange !== "NSE") continue;
    if (!OPEN_STATUSES.has(String(o.status ?? "").trim().toUpperCase())) continue;
    const sym = normalizedSymbol(o.tradingsymbol);
    if (!sym) continue;
    openOrders.push({
      symbol: sym,
      side: String(o.transaction_type ?? "").trim().toUpperCase(),
      quantity: normalizedQuantity(o.quantity),
      status: String(o.status ?? "").trim().toUpperCase(),
    });
  }
  return openOrders;
}

function parseArgs(argv: string[]): { runDir: string } {
  const runDirIndex = argv.indexOf("--run-dir");
  if (runDirIndex === -1 || runDirIndex + 1 >= argv.length) {
    throw new Error("usage: zerodha-live-snapshot.ts --run-dir <path>");
  }
  return { runDir: argv[runDirIndex + 1] };
}

async function main() {
  await import("dotenv/config");
  const { runDir } = parseArgs(process.argv.slice(2));
  const outPath = resolve(process.cwd(), runDir, "live_broker_snapshot.json");
  const tmpPath = `${outPath}.tmp`;

  const [holdings, positions, orders, margins] = await Promise.all([
    kiteRequest<Holding[]>("/portfolio/holdings"),
    kiteRequest<unknown>("/portfolio/positions"),
    kiteRequest<Order[]>("/orders"),
    kiteRequest<EquityMargins>("/user/margins/equity"),
  ]);

  const holdingsMap = buildHoldingsMap(holdings ?? [], positions);
  const openOrders = normalizeOpenOrders(orders ?? []);

  const availableCash = margins?.available?.cash;
  if (!Number.isFinite(availableCash)) {
    throw new Error("equity margins available.cash is missing or non-numeric");
  }

  const snapshot = {
    checked_at: new Date().toISOString(),
    auth_ok: true,
    holdings: holdingsMap,
    open_orders: openOrders,
    available_cash_inr: availableCash as number,
  };

  await mkdir(dirname(outPath), { recursive: true });
  await writeFile(tmpPath, JSON.stringify(snapshot, null, 2) + "\n", "utf-8");
  await rename(tmpPath, outPath);
  console.log("zerodha_live_snapshot=OK");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err: unknown) => {
    const message = err instanceof Error ? err.message : "unknown error";
    const kind = /Kite API 4\d\d/.test(message) ? "AUTH_FAILED" : "FETCH_FAILED";
    console.log(`zerodha_live_snapshot=${kind}`);
    process.exit(1);
  });
}
