#!/usr/bin/env node
import "dotenv/config";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const KITE_BASE_URL = "https://api.kite.trade";

type QueryValue = string | number | boolean | undefined;

function requireCredentials() {
  const apiKey = process.env.ZERODHA_API_KEY;
  const accessToken = process.env.ZERODHA_ACCESS_TOKEN;

  if (!apiKey || !accessToken) {
    throw new Error(
      "Missing ZERODHA_API_KEY or ZERODHA_ACCESS_TOKEN. Add them to .env in /Volumes/D-DRIVE/TradingBot."
    );
  }

  return { apiKey, accessToken };
}

function textJson(value: unknown) {
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(value, null, 2)
      }
    ]
  };
}

function buildUrl(path: string, query?: Record<string, QueryValue | QueryValue[]>) {
  const url = new URL(path, KITE_BASE_URL);

  for (const [key, value] of Object.entries(query ?? {})) {
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined) url.searchParams.append(key, String(item));
      }
      continue;
    }

    if (value !== undefined) url.searchParams.set(key, String(value));
  }

  return url;
}

async function kiteRequest<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PUT" | "DELETE";
    query?: Record<string, QueryValue | QueryValue[]>;
    form?: Record<string, QueryValue>;
  } = {}
): Promise<T> {
  const { apiKey, accessToken } = requireCredentials();
  const method = options.method ?? "GET";
  const headers = new Headers({
    Authorization: `token ${apiKey}:${accessToken}`,
    "X-Kite-Version": "3"
  });

  let body: URLSearchParams | undefined;
  if (options.form) {
    headers.set("Content-Type", "application/x-www-form-urlencoded");
    body = new URLSearchParams();
    for (const [key, value] of Object.entries(options.form)) {
      if (value !== undefined) body.set(key, String(value));
    }
  }

  const response = await fetch(buildUrl(path, options.query), { method, headers, body });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    throw new Error(`Kite API ${response.status}: ${JSON.stringify(data)}`);
  }

  // Kite wraps every success as {status, data:{...}}; callers (and the Python
  // client) expect the unwrapped payload. Fall back to the raw body for any
  // endpoint that doesn't wrap.
  return (data?.data ?? data) as T;
}

const server = new McpServer({
  name: "zerodha-kite-local",
  version: "0.1.0"
});

server.registerTool(
  "zerodha_profile",
  {
    title: "Get Zerodha profile",
    description: "Fetch the authenticated Zerodha Kite user profile.",
    inputSchema: {}
  },
  async () => textJson(await kiteRequest("/user/profile"))
);

server.registerTool(
  "zerodha_margins",
  {
    title: "Get Zerodha margins",
    description: "Fetch account margins. Optionally pass equity or commodity segment.",
    inputSchema: {
      segment: z.enum(["equity", "commodity"]).optional()
    }
  },
  async ({ segment }) => textJson(await kiteRequest(segment ? `/user/margins/${segment}` : "/user/margins"))
);

server.registerTool(
  "zerodha_holdings",
  {
    title: "Get Zerodha holdings",
    description: "Fetch long-term holdings from the demat account.",
    inputSchema: {}
  },
  async () => textJson(await kiteRequest("/portfolio/holdings"))
);

server.registerTool(
  "zerodha_positions",
  {
    title: "Get Zerodha positions",
    description: "Fetch current net and day positions.",
    inputSchema: {}
  },
  async () => textJson(await kiteRequest("/portfolio/positions"))
);

server.registerTool(
  "zerodha_orders",
  {
    title: "Get Zerodha orders",
    description: "Fetch the order book.",
    inputSchema: {}
  },
  async () => textJson(await kiteRequest("/orders"))
);

server.registerTool(
  "zerodha_order_trades",
  {
    title: "Get trades for order",
    description: "Fetch trades executed for a Zerodha order ID.",
    inputSchema: {
      order_id: z.string().min(1)
    }
  },
  async ({ order_id }) => textJson(await kiteRequest(`/orders/${encodeURIComponent(order_id)}/trades`))
);

server.registerTool(
  "zerodha_quote",
  {
    title: "Get Zerodha quote",
    description: "Fetch full market quotes for instruments like NSE:INFY or NFO:NIFTY26MAYFUT.",
    inputSchema: {
      instruments: z.array(z.string().min(1)).min(1).max(50)
    }
  },
  async ({ instruments }) => textJson(await kiteRequest("/quote", { query: { i: instruments } }))
);

server.registerTool(
  "zerodha_ltp",
  {
    title: "Get Zerodha LTP",
    description: "Fetch last traded prices for instruments like NSE:INFY.",
    inputSchema: {
      instruments: z.array(z.string().min(1)).min(1).max(100)
    }
  },
  async ({ instruments }) => textJson(await kiteRequest("/quote/ltp", { query: { i: instruments } }))
);

server.registerTool(
  "zerodha_ohlc",
  {
    title: "Get Zerodha OHLC",
    description: "Fetch OHLC quotes for instruments like NSE:INFY.",
    inputSchema: {
      instruments: z.array(z.string().min(1)).min(1).max(100)
    }
  },
  async ({ instruments }) => textJson(await kiteRequest("/quote/ohlc", { query: { i: instruments } }))
);

server.registerTool(
  "zerodha_place_order",
  {
    title: "Place Zerodha order",
    description:
      "Place a live Zerodha order only when ZERODHA_ENABLE_TRADING=true and confirm=true. Otherwise returns the order payload without sending it.",
    inputSchema: {
      variety: z.enum(["regular", "amo", "co", "iceberg", "auction"]).default("regular"),
      exchange: z.string().min(1),
      tradingsymbol: z.string().min(1),
      transaction_type: z.enum(["BUY", "SELL"]),
      quantity: z.number().int().positive(),
      product: z.enum(["CNC", "NRML", "MIS"]),
      order_type: z.enum(["MARKET", "LIMIT", "SL", "SL-M"]),
      price: z.number().positive().optional(),
      trigger_price: z.number().positive().optional(),
      validity: z.enum(["DAY", "IOC", "TTL"]).optional(),
      disclosed_quantity: z.number().int().positive().optional(),
      tag: z.string().max(20).optional(),
      confirm: z.boolean().default(false)
    }
  },
  async ({ variety, confirm, ...order }) => {
    const payload = { variety, ...order };

    if (process.env.ZERODHA_ENABLE_TRADING !== "true" || !confirm) {
      return textJson({
        dry_run: true,
        reason: "Set ZERODHA_ENABLE_TRADING=true and pass confirm=true to place this live order.",
        payload
      });
    }

    return textJson(
      await kiteRequest(`/orders/${encodeURIComponent(variety)}`, {
        method: "POST",
        form: order
      })
    );
  }
);

const instrumentTokenCache = new Map<string, number>();

server.registerTool(
  "zerodha_instrument_token",
  {
    title: "Resolve instrument token",
    description: "Resolve a Kite instrument_token for exchange+tradingsymbol (e.g. NSE + INFY).",
    inputSchema: {
      exchange: z.string().min(1),
      tradingsymbol: z.string().min(1)
    }
  },
  async ({ exchange, tradingsymbol }) => {
    const key = `${exchange}:${tradingsymbol}`;
    if (instrumentTokenCache.has(key)) {
      return textJson({ instrument_token: instrumentTokenCache.get(key) });
    }
    const { apiKey, accessToken } = requireCredentials();
    const resp = await fetch(buildUrl(`/instruments/${encodeURIComponent(exchange)}`), {
      headers: new Headers({ Authorization: `token ${apiKey}:${accessToken}`, "X-Kite-Version": "3" })
    });
    const csv = await resp.text();
    const rows = csv.split("\n");
    const header = rows[0].split(",");
    const tokIdx = header.indexOf("instrument_token");
    const symIdx = header.indexOf("tradingsymbol");
    for (const row of rows.slice(1)) {
      const cols = row.split(",");
      if (cols[symIdx] === tradingsymbol) {
        const token = Number(cols[tokIdx]);
        instrumentTokenCache.set(key, token);
        return textJson({ instrument_token: token });
      }
    }
    throw new Error(`instrument_token not found for ${key}`);
  }
);

server.registerTool(
  "zerodha_instruments",
  {
    title: "List cash-equity instruments",
    description:
      "List tradeable cash equities for an exchange as [{tradingsymbol, instrument_token}]. " +
      "Keeps the cash segment (segment == exchange, so indices are dropped) and, when mainboard_only " +
      "(default true), drops suffixed non-mainboard series (SME, government securities, bonds, trade-to-trade), " +
      "which on NSE all carry a '-' in the tradingsymbol.",
    inputSchema: {
      exchange: z.string().min(1),
      mainboard_only: z.boolean().default(true)
    }
  },
  async ({ exchange, mainboard_only }) => {
    const { apiKey, accessToken } = requireCredentials();
    const resp = await fetch(buildUrl(`/instruments/${encodeURIComponent(exchange)}`), {
      headers: new Headers({ Authorization: `token ${apiKey}:${accessToken}`, "X-Kite-Version": "3" })
    });
    const csv = await resp.text();
    const rows = csv.split("\n").filter((r) => r.trim().length > 0);
    const header = rows[0].split(",");
    const tokIdx = header.indexOf("instrument_token");
    const symIdx = header.indexOf("tradingsymbol");
    const segIdx = header.indexOf("segment");
    const out: { tradingsymbol: string; instrument_token: number }[] = [];
    for (const row of rows.slice(1)) {
      const cols = row.split(",");
      if (segIdx >= 0 && cols[segIdx] !== exchange) continue; // drop indices (segment INDICES) & derivatives
      const sym = cols[symIdx];
      if (mainboard_only && sym.includes("-")) continue;      // drop SME / gov-sec / bonds / T2T series
      const token = Number(cols[tokIdx]);
      if (!Number.isFinite(token)) continue;
      out.push({ tradingsymbol: sym, instrument_token: token });
    }
    return textJson({ instruments: out });
  }
);

server.registerTool(
  "zerodha_historical",
  {
    title: "Get Zerodha historical candles",
    description:
      "Fetch historical OHLCV candles for an instrument_token. Dates in 'YYYY-MM-DD HH:MM:SS'. interval one of minute/day/3minute/5minute/10minute/15minute/30minute/60minute.",
    inputSchema: {
      instrument_token: z.number().int().positive(),
      from_date: z.string().min(1),
      to_date: z.string().min(1),
      interval: z.enum(["minute", "day", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute"]),
      continuous: z.boolean().default(false),
      oi: z.boolean().default(false)
    }
  },
  async ({ instrument_token, from_date, to_date, interval, continuous, oi }) => {
    const data = await kiteRequest<{ candles: unknown[] }>(
      `/instruments/historical/${instrument_token}/${interval}`,
      { query: { from: from_date, to: to_date, continuous: continuous ? 1 : 0, oi: oi ? 1 : 0 } }
    );
    return textJson(data);
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
