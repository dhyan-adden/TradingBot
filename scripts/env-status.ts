#!/usr/bin/env node
import "dotenv/config";

const keys = [
  "ZERODHA_API_KEY",
  "ZERODHA_API_SECRET",
  "ZERODHA_ACCESS_TOKEN",
  "ZERODHA_ENABLE_TRADING"
];

for (const key of keys) {
  console.log(`${key}=${process.env[key] ? "SET" : "MISSING"}`);
}
