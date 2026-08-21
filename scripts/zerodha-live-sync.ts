#!/usr/bin/env node
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const KITE_BASE_URL = "https://api.kite.trade";
const LIVE_BOOK_SOURCE = "zerodha_order_sync";

type QueryValue = string | number | boolean | undefined;

export interface KiteOrder {
  order_id?: string;
  exchange?: string;
  tradingsymbol?: string;
  transaction_type?: string;
  quantity?: number;
  filled_quantity?: number;
  status?: string;
  tag?: string;
}

export interface LiveFill {
  orderId: string;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
}

interface LiveBookFile {
  positions?: Record<string, unknown>;
  synced_order_ids?: unknown;
}

function requireCredentials() {
  const apiKey = process.env.ZERODHA_API_KEY;
  const accessToken = process.env.ZERODHA_ACCESS_TOKEN;
  if (!apiKey || !accessToken) {
    throw new Error("missing Zerodha credentials");
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

function normalizeSymbol(value: unknown): string {
  return String(value ?? "").trim().toUpperCase();
}

function normalizeQuantity(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? Math.floor(n) : 0;
}

export function tradeloopCompletedFills(orders: KiteOrder[]): LiveFill[] {
  const fills: LiveFill[] = [];
  for (const order of orders ?? []) {
    if (order.exchange !== "NSE") continue;
    if (String(order.tag ?? "").trim().toUpperCase() !== "TRADELOOP") continue;
    if (String(order.status ?? "").trim().toUpperCase() !== "COMPLETE") continue;

    const orderId = String(order.order_id ?? "").trim();
    const symbol = normalizeSymbol(order.tradingsymbol);
    const side = String(order.transaction_type ?? "").trim().toUpperCase();
    const quantity = normalizeQuantity(order.filled_quantity ?? order.quantity);
    if (!orderId || !symbol || (side !== "BUY" && side !== "SELL") || quantity <= 0) continue;
    fills.push({ orderId, symbol, side, quantity });
  }
  return fills;
}

export function applyLiveFills(
  existingPositions: Record<string, number>,
  fills: LiveFill[],
  alreadySynced: Set<string> = new Set()
): { positions: Record<string, number>; syncedOrderIds: string[]; applied: number } {
  const positions: Record<string, number> = {};
  for (const [symbol, quantity] of Object.entries(existingPositions)) {
    const cleanSymbol = normalizeSymbol(symbol);
    const cleanQuantity = normalizeQuantity(quantity);
    if (cleanSymbol && cleanQuantity > 0) positions[cleanSymbol] = cleanQuantity;
  }

  const synced = new Set(alreadySynced);
  let applied = 0;
  for (const fill of fills) {
    if (synced.has(fill.orderId)) continue;
    const current = positions[fill.symbol] ?? 0;
    if (fill.side === "BUY") {
      positions[fill.symbol] = current + fill.quantity;
    } else {
      if (fill.quantity > current) {
        throw new Error(`SELL ${fill.symbol} exceeds live book quantity`);
      }
      const next = current - fill.quantity;
      if (next > 0) positions[fill.symbol] = next;
      else delete positions[fill.symbol];
    }
    synced.add(fill.orderId);
    applied += 1;
  }

  return { positions, syncedOrderIds: [...synced].sort(), applied };
}

function parseArgs(argv: string[]): { root: string } {
  const rootIndex = argv.indexOf("--root");
  return { root: rootIndex >= 0 && rootIndex + 1 < argv.length ? argv[rootIndex + 1] : "tradeloop" };
}

async function loadLiveBook(path: string): Promise<{ positions: Record<string, number>; synced: Set<string> }> {
  try {
    const data = JSON.parse(await readFile(path, "utf-8")) as LiveBookFile;
    const positions: Record<string, number> = {};
    for (const [symbol, quantity] of Object.entries(data.positions ?? {})) {
      const cleanSymbol = normalizeSymbol(symbol);
      const cleanQuantity = normalizeQuantity(quantity);
      if (!cleanSymbol) continue;
      if (cleanQuantity < 0) throw new Error("negative live-book quantity");
      if (cleanQuantity > 0) positions[cleanSymbol] = cleanQuantity;
    }
    const synced = Array.isArray(data.synced_order_ids)
      ? new Set(data.synced_order_ids.map((item) => String(item)))
      : new Set<string>();
    return { positions, synced };
  } catch (error: unknown) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { positions: {}, synced: new Set() };
    throw error;
  }
}

async function persistLiveBook(path: string, positions: Record<string, number>, syncedOrderIds: string[]) {
  const tmpPath = `${path}.tmp`;
  const payload = {
    updated_at: new Date().toISOString(),
    positions,
    source: LIVE_BOOK_SOURCE,
    synced_order_ids: syncedOrderIds,
  };
  await mkdir(dirname(path), { recursive: true });
  await writeFile(tmpPath, JSON.stringify(payload, null, 2) + "\n", "utf-8");
  await rename(tmpPath, path);
}

async function main() {
  await import("dotenv/config");
  const { root } = parseArgs(process.argv.slice(2));
  const liveBookPath = resolve(process.cwd(), root, "state", "live_book.json");
  const orders = await kiteRequest<KiteOrder[]>("/orders");
  const fills = tradeloopCompletedFills(orders ?? []);
  const current = await loadLiveBook(liveBookPath);
  const next = applyLiveFills(current.positions, fills, current.synced);
  await persistLiveBook(liveBookPath, next.positions, next.syncedOrderIds);
  console.log(`zerodha_live_sync=OK applied=${next.applied}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err: unknown) => {
    const message = err instanceof Error ? err.message : "unknown error";
    const kind = /Kite API 4\d\d/.test(message) ? "AUTH_FAILED" : "SYNC_FAILED";
    console.log(`zerodha_live_sync=${kind}`);
    process.exit(1);
  });
}
