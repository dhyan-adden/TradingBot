import assert from "node:assert/strict";

import {
  applyLiveFills,
  tradeloopCompletedFills,
} from "./zerodha-live-sync.ts";

const fills = tradeloopCompletedFills([
  {
    order_id: "1",
    exchange: "NSE",
    tradingsymbol: "reliance",
    transaction_type: "BUY",
    quantity: 1,
    filled_quantity: 1,
    status: "COMPLETE",
    tag: "TRADELOOP",
  },
  {
    order_id: "2",
    exchange: "NSE",
    tradingsymbol: "SBIN",
    transaction_type: "BUY",
    quantity: 1,
    status: "OPEN",
    tag: "TRADELOOP",
  },
  {
    order_id: "3",
    exchange: "NSE",
    tradingsymbol: "INFY",
    transaction_type: "BUY",
    quantity: 1,
    status: "COMPLETE",
    tag: "MANUAL",
  },
]);

assert.deepEqual(fills, [{ orderId: "1", symbol: "RELIANCE", side: "BUY", quantity: 1 }]);

assert.deepEqual(
  applyLiveFills({ RELIANCE: 1 }, [
    { orderId: "2", symbol: "RELIANCE", side: "BUY", quantity: 2 },
    { orderId: "3", symbol: "RELIANCE", side: "SELL", quantity: 1 },
  ]),
  { positions: { RELIANCE: 2 }, syncedOrderIds: ["2", "3"], applied: 2 }
);

assert.deepEqual(
  applyLiveFills(
    { RELIANCE: 1 },
    [{ orderId: "2", symbol: "RELIANCE", side: "BUY", quantity: 2 }],
    new Set(["2"])
  ),
  { positions: { RELIANCE: 1 }, syncedOrderIds: ["2"], applied: 0 }
);

assert.throws(
  () => applyLiveFills({}, [{ orderId: "4", symbol: "RELIANCE", side: "SELL", quantity: 1 }]),
  /exceeds live book/
);

console.log("zerodha_live_sync_test=OK");
