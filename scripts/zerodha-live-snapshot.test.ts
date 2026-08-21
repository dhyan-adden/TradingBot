import assert from "node:assert/strict";

import {
  buildHoldingsMap,
  normalizeOpenOrders,
  normalizePositionsResponse,
} from "./zerodha-live-snapshot.ts";

const arrayPositions = [
  { exchange: "NSE", tradingsymbol: "RELIANCE", quantity: 1 },
];
assert.deepEqual(normalizePositionsResponse(arrayPositions), arrayPositions);

const kitePositions = {
  net: [{ exchange: "NSE", tradingsymbol: "INFY", quantity: 2 }],
  day: [{ exchange: "NSE", tradingsymbol: "INFY", quantity: 1 }],
};
assert.equal(normalizePositionsResponse(kitePositions).length, 2);

assert.throws(() => normalizePositionsResponse({ net: "bad" }), /unexpected positions/);

assert.deepEqual(
  buildHoldingsMap(
    [{ exchange: "NSE", tradingsymbol: "RELIANCE", quantity: 5 }],
    { net: [{ exchange: "NSE", tradingsymbol: "RELIANCE", quantity: 2 }] }
  ),
  { RELIANCE: 5 }
);

assert.deepEqual(
  buildHoldingsMap(
    [{ exchange: "NSE", tradingsymbol: "RELIANCE", quantity: 1 }],
    { net: [{ exchange: "NSE", tradingsymbol: "RELIANCE", quantity: 3 }] }
  ),
  { RELIANCE: 3 }
);

assert.deepEqual(
  normalizeOpenOrders([
    { exchange: "NSE", tradingsymbol: "SBIN", transaction_type: "BUY", quantity: 1, status: "OPEN" },
    { exchange: "NSE", tradingsymbol: "SBIN", transaction_type: "BUY", quantity: 1, status: "COMPLETE" },
    { exchange: "BSE", tradingsymbol: "SBIN", transaction_type: "BUY", quantity: 1, status: "OPEN" },
  ]),
  [{ symbol: "SBIN", side: "BUY", quantity: 1, status: "OPEN" }]
);

console.log("zerodha_live_snapshot_test=OK");
