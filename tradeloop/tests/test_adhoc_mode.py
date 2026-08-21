import subprocess
from pathlib import Path

import yaml

from tradeloop.scripts import prepare_cycle, verify_setup


def write_minimal_root(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "memory").mkdir()
    (root / "runs").mkdir()
    (root / "config" / "settings.yaml").write_text(
        yaml.safe_dump(
            {
                "modes": {
                    "premarket": {"enabled": True},
                    "intraday": {"enabled": True},
                    "postclose": {"enabled": True},
                    "adhoc": {"enabled": True, "user_request_required": True},
                },
                "capital": {"paper_starting_inr": 100000},
            }
        ),
        encoding="utf-8",
    )
    (root / "memory" / "macro_view.md").write_text("# Macro\n", encoding="utf-8")


def test_verify_setup_accepts_adhoc(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "tradeloop"
    write_minimal_root(root)
    monkeypatch.setattr(verify_setup, "ROOT", root)

    assert verify_setup.verify("adhoc") == 0


def _stub_ingest_run(as_of, run_dir, config_dir):
    # V3-hermeticity: prepare() now calls the real (network-hitting) ingest_run;
    # these tests only assert run-dir scaffolding, so keep them offline.
    Path(run_dir, "01_news_raw.md").write_text("# Raw News\n", encoding="utf-8")
    Path(run_dir, "02_setups_raw.md").write_text("# Raw Technical Setups\n", encoding="utf-8")


def test_prepare_adhoc_writes_user_request(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "tradeloop"
    write_minimal_root(root)
    monkeypatch.setattr(prepare_cycle, "ROOT", root)
    monkeypatch.setattr(prepare_cycle, "ingest_run", _stub_ingest_run)

    run_dir = prepare_cycle.prepare("adhoc", "Analyze INFY for a long-only swing setup")

    assert (run_dir / "user_request.md").read_text(encoding="utf-8").endswith("Analyze INFY for a long-only swing setup\n")
    assert (run_dir / "05_adhoc_intake.md").exists()
    assert (run_dir / "orders.json").read_text(encoding="utf-8") == "[]\n"


def test_prepare_adhoc_requires_request(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "tradeloop"
    write_minimal_root(root)
    monkeypatch.setattr(prepare_cycle, "ROOT", root)
    monkeypatch.setattr(prepare_cycle, "ingest_run", _stub_ingest_run)

    try:
        prepare_cycle.prepare("adhoc", "")
    except ValueError as exc:
        assert "requires --request" in str(exc)
    else:
        raise AssertionError("adhoc prepare should require request text")


def test_prepare_renders_open_positions_into_context(monkeypatch, tmp_path: Path) -> None:
    # kills a regression where 00_context always rendered an EMPTY book: agents
    # reasoned over a flat portfolio while the ledger held open positions, so
    # manage-mode cycles could never see (or exit) what they were holding.
    from tradeloop.lib.broker.paper_book import append as append_book
    from tradeloop.lib.broker.paper_broker import Fill

    root = tmp_path / "tradeloop"
    write_minimal_root(root)
    (root / "state").mkdir()
    append_book(
        root / "state" / "ledger.db",
        [Fill("PAPER-1", "HDFCBANK", "BUY", 30, 830.62, "FILLED", "CNC")],
        hard_stops={"HDFCBANK": 807.24},
    )
    monkeypatch.setattr(prepare_cycle, "ROOT", root)
    monkeypatch.setattr(prepare_cycle, "ingest_run", _stub_ingest_run)

    run_dir = prepare_cycle.prepare("intraday", "")

    context = (run_dir / "00_context.md").read_text(encoding="utf-8")
    assert "HDFCBANK: quantity=30, avg_price=830.62, hard_stop=807.24" in context
    assert "- None" not in context
    # cash = start - notional - exchange costs (stamp/charges), so strictly
    # below the naive figure but within a small cost band of it
    cash = float(context.split("Cash INR: ")[1].split("\n")[0])
    naive = 100000 - 30 * 830.62
    assert naive - 35 < cash < naive


def test_prepare_without_ledger_renders_empty_book(monkeypatch, tmp_path: Path) -> None:
    # fresh deploys / hermetic roots have no state/ledger.db: prepare must fall
    # back to the empty starting book, not crash or invent positions.
    root = tmp_path / "tradeloop"
    write_minimal_root(root)
    monkeypatch.setattr(prepare_cycle, "ROOT", root)
    monkeypatch.setattr(prepare_cycle, "ingest_run", _stub_ingest_run)

    run_dir = prepare_cycle.prepare("premarket", "")

    context = (run_dir / "00_context.md").read_text(encoding="utf-8")
    assert "- None" in context
    assert "Cash INR: 100000" in context


def test_run_cycle_adhoc_missing_request_exits_before_codex() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["bash", "tradeloop/scripts/run_cycle.sh", "adhoc"],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "usage:" in result.stderr
