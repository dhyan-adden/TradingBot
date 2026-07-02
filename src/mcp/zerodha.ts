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

  return data as T;
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

const transport = new StdioServerTransport();
await server.connect(transport);
