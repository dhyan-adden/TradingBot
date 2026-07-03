import importlib
import json
from datetime import date

from tradeloop.lib.util.holidays import NSE_HOLIDAYS_2026, is_nse_holiday


def test_tradeloop_package_is_importable() -> None:
    # tradeloop must be a real importable package (packaging fix), not only
    # reachable via a sys.path hack inside scripts.
    mod = importlib.import_module("tradeloop.lib.broker.paper_broker")
    assert hasattr(mod, "PaperBroker")
    orch = importlib.import_module("tradeloop.orchestrator")
    assert hasattr(orch, "main")


def test_nse_2026_holiday_gate() -> None:
    assert is_nse_holiday(date(2026, 1, 26)) is True   # Republic Day
    assert is_nse_holiday(date(2026, 6, 26)) is True   # Muharram
    assert is_nse_holiday(date(2026, 3, 26)) is True   # Ram Navami (Thu — corrected date)
    assert is_nse_holiday(date(2026, 7, 1)) is False   # ordinary Wednesday
    assert is_nse_holiday(date(2026, 7, 4)) is True    # Saturday — weekend gate
    assert len(NSE_HOLIDAYS_2026) == 16


from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def test_master_prompt_hands_routing_to_python() -> None:
    text = (PROMPTS / "00_master_orchestrator.md").read_text(encoding="utf-8").lower()
    assert "do not route orders" in text
    assert "does not write fills.json" in text or "do not write fills.json" in text


def test_pm_prompt_writes_orders_only_not_fills() -> None:
    text = (PROMPTS / "41_portfolio_manager.md").read_text(encoding="utf-8").lower()
    assert "orders.json" in text
    assert "do not write" in text and "fills.json" in text


from tradeloop import orchestrator


def test_run_reasoning_is_a_seam(monkeypatch, tmp_path) -> None:
    calls = {}

    def fake(run_dir, mode, agent):
        calls["run_dir"] = run_dir
        calls["mode"] = mode
        return 0

    monkeypatch.setattr(orchestrator, "_run_reasoning", fake)
    rc = orchestrator._run_reasoning(tmp_path, "premarket", "codex")
    assert rc == 0
    assert calls["mode"] == "premarket"


def _fresh_root(tmp_path):
    """Copy the minimal config the orchestrator reads into an isolated root."""
    import shutil
    root = tmp_path / "tradeloop"
    (root / "config").mkdir(parents=True)
    (root / "state").mkdir()
    src = Path(__file__).resolve().parents[1]
    shutil.copy(src / "config" / "settings.yaml", root / "config" / "settings.yaml")
    shutil.copy(src / "config" / "universe.yaml", root / "config" / "universe.yaml")
    return root


def test_holiday_halts_before_reasoning(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    called = {"reasoned": False}
    monkeypatch.setattr(orchestrator, "_run_reasoning", lambda *a, **k: called.__setitem__("reasoned", True) or 0)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 1, 26))  # Republic Day
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0
    assert called["reasoned"] is False


def test_kill_switch_halts_before_reasoning(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    (root / "kill_switch.md").write_text("halt", encoding="utf-8")
    called = {"reasoned": False}
    monkeypatch.setattr(orchestrator, "_run_reasoning", lambda *a, **k: called.__setitem__("reasoned", True) or 0)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0
    assert called["reasoned"] is False


def test_malformed_orders_aborts_loud(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_reason(run_dir, mode, agent, timeout):
        (run_dir / "orders.json").write_text("{not json", encoding="utf-8")
        return 0

    def fake_prepare(mode, request="", root=None):
        run_dir = root / "runs" / f"test_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 1


def test_run_reasoning_pins_run_dir_env(monkeypatch, tmp_path) -> None:
    # run_cycle.sh must be told which run dir to use, or it re-prepares its own
    # (minute-boundary divergence -> silent no-op cycle).
    captured = {}

    def fake_run(argv, env=None, cwd=None, timeout=None):
        captured["argv"] = argv
        captured["env"] = env

        class Proc:
            returncode = 0

        return Proc()

    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)
    rc = orchestrator._run_reasoning(tmp_path, "premarket", "codex", timeout=5)
    assert rc == 0
    assert captured["env"]["TRADELOOP_RUN_DIR"] == str(tmp_path)
    assert captured["argv"][2] == "premarket"


def test_run_reasoning_passes_agent_to_backend(monkeypatch, tmp_path) -> None:
    # Agent-agnostic: whichever backend is chosen must reach run_cycle.sh's
    # TRADELOOP_AGENT switch. A non-default value proves it is not hardcoded.
    captured = {}

    def fake_run(argv, env=None, cwd=None, timeout=None):
        captured["env"] = env

        class Proc:
            returncode = 0

        return Proc()

    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)
    orchestrator._run_reasoning(tmp_path, "premarket", "claude", timeout=5)
    assert captured["env"]["TRADELOOP_AGENT"] == "claude"


def test_cli_agent_flag_selects_backend(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(orchestrator, "run_cycle",
                        lambda mode, request, agent=None: seen.update(agent=agent) or 0)
    orchestrator.main(["premarket", "--agent", "claude"])
    assert seen["agent"] == "claude"


def test_end_to_end_gate_runs_on_every_order(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_prepare(mode, request="", root=None):
        run_dir = root / "runs" / f"e2e_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def fake_reason(run_dir, mode, agent, timeout):
        # One approved BUY (in universe, >= min_position_size 15000, under the
        # 25% allocation cap of the 100000 starting equity) + one non-universe reject.
        (run_dir / "orders.json").write_text(json.dumps({"orders": [
            {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000, "hard_stop": 950.0},
            {"ticker": "FAKECO", "side": "BUY", "quantity": 1, "price": 5000},
        ]}), encoding="utf-8")
        return 0

    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0

    run_dir = root / "runs" / "e2e_premarket"
    fills = json.loads((run_dir / "fills.json").read_text(encoding="utf-8"))
    statuses = {f.get("status") for f in fills}
    assert "FILLED" in statuses            # approved order routed
    assert "RISK_REJECTED" in statuses     # non-universe order gated
    decisions = (run_dir / "decisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(decisions) == 2             # gate logged its own verdict per order

    # Persistence: the FILLED fill (and its hard_stop) reached the book, so the
    # NEXT cycle's hydrate sees the position — spec acceptance #3.
    book_lines = (root / "state" / "paper_book.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(book_lines) == 1
    rec = json.loads(book_lines[0])
    assert rec["symbol"] == "RELIANCE" and rec["status"] == "FILLED" and rec["hard_stop"] == 950.0
    rehydrated = orchestrator.hydrate(root / "state" / "paper_book.jsonl", 100000)
    assert rehydrated.positions == {"RELIANCE": 20}
