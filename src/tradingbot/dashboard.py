import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from tradingbot.broker.paper import PaperBroker
from tradingbot.config import load_config
from tradingbot.event_log import Event, EventLog
from tradingbot.order_gate import latest_order_gate_mode, set_order_gate_mode


def latest_marks(events: List[Event]) -> Dict[str, float]:
    marks: Dict[str, float] = {}
    for event in events:
        if event.event_type == "paper.position.marked":
            symbol = str(event.payload.get("symbol", "")).upper()
            if symbol:
                marks[symbol] = float(event.payload.get("last_price", 0))
    return marks


def latest_event(events: List[Event], event_type: str) -> Event | None:
    return next((event for event in reversed(events) if event.event_type == event_type), None)


def latest_event_with_prefix(events: List[Event], prefix: str) -> Event | None:
    return next((event for event in reversed(events) if event.event_type.startswith(prefix)), None)


def pending_order_gates(events: List[Event]) -> List[Dict[str, Any]]:
    finished: set[str] = set()
    pending: List[Dict[str, Any]] = []
    for event in events:
        if event.event_type in {"order_gate.approved", "order_gate.cancelled", "order_gate.blocked"}:
            finished.add(event.aggregate_id)
    for event in reversed(events):
        if event.event_type != "order_gate.pending" or event.aggregate_id in finished:
            continue
        request = event.payload.get("request", {})
        pending.append(
            {
                "gate_id": event.aggregate_id,
                "created_at": event.created_at,
                "mode": event.payload.get("mode"),
                "symbol": request.get("symbol"),
                "side": request.get("side"),
                "quantity": request.get("quantity"),
                "price": request.get("price"),
                "strategy": request.get("strategy"),
                "cancel_window_seconds": event.payload.get("cancel_window_seconds"),
            }
        )
    return pending


def dashboard_payload(config_dir: Path) -> Dict[str, Any]:
    config = load_config(config_dir)
    event_log = EventLog(Path(config.raw["system"]["state"]["sqlite_path"]))
    broker = PaperBroker(
        event_log=event_log,
        starting_cash_inr=float(config.raw["paper_broker"].get("starting_cash_inr", 100000)),
        order_prefix=str(config.raw["paper_broker"].get("order_id_prefix", "PAPER")),
    )
    events = list(event_log.replay())
    portfolio = broker.portfolio()
    marks = latest_marks(events)
    positions = []
    for symbol, quantity in sorted(portfolio.positions.items()):
        avg_price = portfolio.avg_prices.get(symbol, 0.0)
        last_price = marks.get(symbol, avg_price)
        positions.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": avg_price,
                "last_price": last_price,
                "unrealized_pnl_inr": round(quantity * (last_price - avg_price), 2),
                "market_value_inr": round(quantity * last_price, 2),
            }
        )

    market_value = sum(item["market_value_inr"] for item in positions)
    latest_quote = latest_event(events, "data.quote_received") or latest_event(events, "market.quote_received")
    latest_signal = latest_event(events, "signal.generated")
    latest_loop = latest_event(events, "loop.heartbeat")
    latest_agent_loop = latest_event(events, "agent_loop.heartbeat")
    latest_learning = latest_event_with_prefix(events, "learning.")
    latest_research = latest_event(events, "research.trend_summary_written")
    latest_trader = latest_event(events, "agent.trader_proposal_written")
    latest_portfolio = latest_event(events, "agent.portfolio_decision_written")
    latest_veto = latest_event(events, "agent.vetoed")
    latest_shortlist = latest_event(events, "research.shortlist_generated")
    latest_autonomous = latest_event(events, "autonomous_loop.heartbeat")
    latest_server_error = latest_event(events, "autonomous_server.error")
    latest_market_session = latest_event(events, "market.session_checked")
    kill_event = event_log.latest("system.kill_switch")
    memory_root = Path(config.raw["system"]["state"]["memory_root"])
    gate_config = config.raw["loop"].get("execution", {}).get("order_gate", {})
    order_gate_mode = latest_order_gate_mode(event_log, str(gate_config.get("mode", "autopilot")))

    return {
        "portfolio": {
            "cash_inr": portfolio.cash_inr,
            "market_value_inr": round(market_value, 2),
            "equity_inr": round(portfolio.cash_inr + market_value, 2),
            "realized_pnl_inr": portfolio.realized_pnl_inr,
            "open_positions": len(positions),
            "positions": positions,
        },
        "market": {
            "latest_quote": latest_quote.payload if latest_quote else None,
            "latest_quote_at": latest_quote.created_at if latest_quote else None,
            "data_source": config.raw["system"].get("data", {}).get("quote_source", "unknown"),
            "session": latest_market_session.payload if latest_market_session else None,
        },
        "system": {
            "mode": config.system.mode,
            "broker": config.system.broker,
            "kill_switch": bool(kill_event and kill_event.payload.get("active")),
            "event_count": len(events),
        },
        "loop": {
            "last_heartbeat": (latest_autonomous or latest_agent_loop or latest_loop).created_at if (latest_autonomous or latest_agent_loop or latest_loop) else None,
            "last_cycle": (latest_autonomous or latest_agent_loop or latest_loop).payload.get("cycle") if (latest_autonomous or latest_agent_loop or latest_loop) else None,
            "latest_signal": latest_signal.payload if latest_signal else None,
            "latest_learning": latest_learning.payload if latest_learning else None,
            "latest_research": latest_research.payload if latest_research else None,
            "latest_trader": latest_trader.payload if latest_trader else None,
            "latest_portfolio": latest_portfolio.payload if latest_portfolio else None,
            "latest_veto": latest_veto.payload if latest_veto else None,
            "latest_shortlist": latest_shortlist.payload if latest_shortlist else None,
            "latest_error": latest_server_error.payload if latest_server_error else None,
        },
        "order_gate": {
            "mode": order_gate_mode,
            "cancel_window_seconds": float(gate_config.get("cancel_window_seconds", 30)),
            "pending": pending_order_gates(events),
        },
        "memory": {
            "daily_files": len(list((memory_root / "daily").glob("*.md"))),
            "trade_files": len(list((memory_root / "trades").glob("*.md"))),
            "lesson_files": len(list((memory_root / "lessons").glob("*.md"))),
            "proposal_files": len(list((memory_root / "proposals").glob("*.md"))),
            "scorecard_files": len(list((memory_root / "scorecards").glob("*.md"))),
        },
        "events": [
            {
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "created_at": event.created_at,
                "event_hash": event.event_hash[:12],
                "payload": event.payload,
            }
            for event in events[-50:][::-1]
        ],
    }


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TradingBot Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #637083;
      --line: #d8dde6;
      --good: #16794c;
      --bad: #b42318;
      --accent: #1f6feb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { margin: 0; font-size: 20px; font-weight: 700; }
    .subtle { color: var(--muted); font-size: 13px; }
    main { padding: 20px 24px 32px; max-width: 1280px; margin: 0 auto; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .card, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .card .label { color: var(--muted); font-size: 12px; }
    .card .value { margin-top: 8px; font-size: 24px; font-weight: 750; }
    .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .section { margin-top: 16px; }
    .panel h2 { margin: 0 0 12px; font-size: 16px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
    th { color: var(--muted); font-weight: 650; }
    .pos { color: var(--good); }
    .neg { color: var(--bad); }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 24px;
      padding: 0 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      font-size: 12px;
      color: var(--muted);
      background: #fafbfc;
      white-space: nowrap;
    }
    .live-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--good);
      display: inline-block;
      animation: pulse 1.6s ease-in-out infinite;
    }
    .warn-dot { background: #d97706; }
    @keyframes pulse {
      0%, 100% { opacity: .35; transform: scale(.85); }
      50% { opacity: 1; transform: scale(1); }
    }
    .event-type { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      color: var(--muted);
    }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 7px;
      padding: 8px 10px;
      color: var(--ink);
      cursor: pointer;
    }
    button:hover { border-color: var(--accent); }
    @media (max-width: 900px) {
      header { align-items: flex-start; flex-direction: column; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      main { padding: 14px; }
      table { min-width: 720px; }
      .scroll { overflow-x: auto; }
    }
    @media (max-width: 520px) {
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>TradingBot Paper Dashboard</h1>
      <div class="subtle" id="meta">Loading local paper state...</div>
    </div>
    <div class="row">
      <span class="pill" id="refreshState"><span class="live-dot"></span> Live</span>
      <button type="button" onclick="load()">Refresh</button>
    </div>
  </header>
  <main>
    <section class="grid">
      <div class="card"><div class="label">Equity</div><div class="value" id="equity">-</div></div>
      <div class="card"><div class="label">Cash</div><div class="value" id="cash">-</div></div>
      <div class="card"><div class="label">Realized P&L</div><div class="value" id="realized">-</div></div>
      <div class="card"><div class="label">Open Positions</div><div class="value" id="positionsCount">-</div></div>
    </section>

    <section class="section panel">
      <div class="row">
        <h2>Market</h2>
        <span class="pill" id="killSwitch">Kill switch: -</span>
      </div>
      <div class="subtle" id="latestQuote">No quote yet.</div>
      <div class="subtle" id="activity">Waiting for loop activity.</div>
    </section>

    <section class="section panel">
      <div class="row">
        <h2>Order Gate</h2>
        <div>
          <button type="button" onclick="setGateMode('autopilot')">Auto Pilot</button>
          <button type="button" onclick="setGateMode('confirm_each_order')">Confirm</button>
          <button type="button" onclick="setGateMode('paused')">Pause</button>
        </div>
      </div>
      <div class="subtle" id="gateMode">Mode: -</div>
      <div class="scroll">
        <table>
          <thead>
            <tr><th>Gate</th><th>Order</th><th>Mode</th><th>Action</th></tr>
          </thead>
          <tbody id="pendingGates"></tbody>
        </table>
      </div>
    </section>

    <section class="section panel">
      <h2>Autonomous Agents</h2>
      <div class="grid">
        <div class="card"><div class="label">Shortlist</div><div class="value" id="shortlistCount">-</div></div>
        <div class="card"><div class="label">Last Cycle</div><div class="value" id="lastCycle">-</div></div>
        <div class="card"><div class="label">Trader</div><div class="value" id="traderAction">-</div></div>
        <div class="card"><div class="label">Portfolio</div><div class="value" id="portfolioAllow">-</div></div>
      </div>
      <pre id="agentDetails" class="section"></pre>
    </section>

    <section class="section panel">
      <h2>Positions</h2>
      <div class="scroll">
        <table>
          <thead>
            <tr><th>Symbol</th><th>Qty</th><th>Avg</th><th>Last</th><th>Value</th><th>Unrealized P&L</th></tr>
          </thead>
          <tbody id="positions"></tbody>
        </table>
      </div>
    </section>

    <section class="section panel">
      <h2>Memory Files</h2>
      <div class="grid">
        <div class="card"><div class="label">Daily</div><div class="value" id="dailyFiles">-</div></div>
        <div class="card"><div class="label">Trades</div><div class="value" id="tradeFiles">-</div></div>
        <div class="card"><div class="label">Lessons</div><div class="value" id="lessonFiles">-</div></div>
        <div class="card"><div class="label">Proposals</div><div class="value" id="proposalFiles">-</div></div>
      </div>
    </section>

    <section class="section panel">
      <h2>Recent Events</h2>
      <div class="scroll">
        <table>
          <thead>
            <tr><th>Time</th><th>Type</th><th>Aggregate</th><th>Payload</th></tr>
          </thead>
          <tbody id="events"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
    const number = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });
    let lastEventCount = null;
    function pnlClass(value) { return Number(value) < 0 ? 'neg' : 'pos'; }
    function setText(id, value) { document.getElementById(id).textContent = value; }
    async function postJson(path, body) {
      await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
      await load();
    }
    function setGateMode(mode) { return postJson('/api/order-gate/mode', { mode }); }
    function approveGate(gateId) { return postJson(`/api/order-gate/${gateId}/approve`, { reason: 'dashboard_approved' }); }
    function cancelGate(gateId) { return postJson(`/api/order-gate/${gateId}/cancel`, { reason: 'dashboard_cancelled' }); }
    function render(data) {
      const p = data.portfolio;
      setText('equity', inr.format(p.equity_inr));
      setText('cash', inr.format(p.cash_inr));
      const realized = document.getElementById('realized');
      realized.textContent = inr.format(p.realized_pnl_inr);
      realized.className = 'value ' + pnlClass(p.realized_pnl_inr);
      setText('positionsCount', p.open_positions);
      const now = new Date().toLocaleTimeString();
      const eventDelta = lastEventCount === null ? 0 : data.system.event_count - lastEventCount;
      lastEventCount = data.system.event_count;
      setText('meta', `${data.system.mode} mode · ${data.market.data_source} data · ${data.system.event_count} events · refreshed ${now}`);
      document.getElementById('refreshState').innerHTML = `<span class="live-dot ${eventDelta < 0 ? 'warn-dot' : ''}"></span>${eventDelta > 0 ? `+${eventDelta} events` : 'Live'}`;
      setText('killSwitch', `Kill switch: ${data.system.kill_switch ? 'ON' : 'OFF'}`);
      const quote = data.market.latest_quote;
      const session = data.market.session;
      const phase = session ? ` · ${session.phase} · ${session.reason}` : '';
      setText('latestQuote', quote ? `${quote.symbol} last ${inr.format(quote.last_price)} from ${quote.source} at ${data.market.latest_quote_at}${phase}` : `No quote yet.${phase}`);
      const latestEvent = data.events[0];
      setText('activity', latestEvent ? `Latest activity: ${latestEvent.event_type} at ${latestEvent.created_at}` : 'No event activity yet.');
      const gate = data.order_gate;
      setText('gateMode', `Mode: ${gate.mode} · cancel window ${gate.cancel_window_seconds}s`);
      document.getElementById('pendingGates').innerHTML = gate.pending.length ? gate.pending.map(item => `
        <tr>
          <td><span class="event-type">${item.gate_id}</span><div class="subtle">${item.created_at}</div></td>
          <td>${item.side} ${item.quantity} ${item.symbol} @ ${inr.format(item.price || 0)}<div class="subtle">${item.strategy || ''}</div></td>
          <td>${item.mode}</td>
          <td><button type="button" onclick="approveGate('${item.gate_id}')">Approve</button> <button type="button" onclick="cancelGate('${item.gate_id}')">Cancel</button></td>
        </tr>`).join('') : '<tr><td colspan="4" class="subtle">No orders waiting at the gate.</td></tr>';
      const shortlist = data.loop.latest_shortlist;
      const trader = data.loop.latest_trader;
      const portfolio = data.loop.latest_portfolio;
      setText('shortlistCount', shortlist ? shortlist.symbols.length : 0);
      setText('lastCycle', data.loop.last_cycle || '-');
      setText('traderAction', trader ? trader.action : '-');
      setText('portfolioAllow', portfolio ? (portfolio.allow_trade ? 'Allowed' : 'Vetoed') : '-');
      document.getElementById('agentDetails').textContent = JSON.stringify({
        shortlist: shortlist ? shortlist.candidates : [],
        trader,
        portfolio,
        veto: data.loop.latest_veto,
        error: data.loop.latest_error,
      }, null, 2);
      setText('dailyFiles', data.memory.daily_files);
      setText('tradeFiles', data.memory.trade_files);
      setText('lessonFiles', data.memory.lesson_files);
      setText('proposalFiles', data.memory.proposal_files);
      document.getElementById('positions').innerHTML = p.positions.length ? p.positions.map(pos => `
        <tr>
          <td>${pos.symbol}</td>
          <td>${number.format(pos.quantity)}</td>
          <td>${inr.format(pos.avg_price)}</td>
          <td>${inr.format(pos.last_price)}</td>
          <td>${inr.format(pos.market_value_inr)}</td>
          <td class="${pnlClass(pos.unrealized_pnl_inr)}">${inr.format(pos.unrealized_pnl_inr)}</td>
        </tr>`).join('') : '<tr><td colspan="6" class="subtle">No open paper positions.</td></tr>';
      document.getElementById('events').innerHTML = data.events.map(event => `
        <tr>
          <td>${event.created_at}</td>
          <td><span class="event-type">${event.event_type}</span></td>
          <td>${event.aggregate_id}</td>
          <td><pre>${JSON.stringify(event.payload, null, 2)}</pre></td>
        </tr>`).join('');
    }
    async function load() {
      const response = await fetch('/api/status', { cache: 'no-store' });
      render(await response.json());
    }
    function startStream() {
      if (!window.EventSource) {
        setInterval(load, 1000);
        return;
      }
      const source = new EventSource('/api/stream');
      source.onmessage = event => render(JSON.parse(event.data));
      source.onerror = () => {
        source.close();
        setInterval(load, 1000);
      };
    }
    load();
    startStream();
  </script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    config_dir = Path("config")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/status":
            body = json.dumps(dashboard_payload(self.config_dir), indent=2).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if path == "/api/stream":
            self._stream()
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        config = load_config(self.config_dir)
        event_log = EventLog(Path(config.raw["system"]["state"]["sqlite_path"]))
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, b"invalid json", "text/plain; charset=utf-8")
            return
        if path == "/api/order-gate/mode":
            mode = str(payload.get("mode", ""))
            try:
                set_order_gate_mode(event_log, mode)
            except ValueError as exc:
                self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                return
            self._send(200, b'{"ok": true}', "application/json; charset=utf-8")
            return
        parts = [part for part in path.split("/") if part]
        if len(parts) == 4 and parts[:2] == ["api", "order-gate"] and parts[3] in {"approve", "cancel"}:
            gate_id = parts[2]
            reason = str(payload.get("reason", "dashboard"))
            event_type = "order_gate.approved" if parts[3] == "approve" else "order_gate.cancelled"
            status = "APPROVED" if parts[3] == "approve" else "CANCELLED_BY_USER"
            event_log.append_event(event_type, gate_id, {"gate_id": gate_id, "status": status, "reason": reason})
            self._send(200, b'{"ok": true}', "application/json; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        while True:
            payload = json.dumps(dashboard_payload(self.config_dir), separators=(",", ":"))
            try:
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(1)


def serve_dashboard(host: str, port: int, config_dir: Path) -> None:
    DashboardHandler.config_dir = config_dir
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"dashboard=http://{host}:{port}")
    server.serve_forever()
