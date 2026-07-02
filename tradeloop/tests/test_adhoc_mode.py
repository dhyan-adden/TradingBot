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


def test_prepare_adhoc_writes_user_request(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "tradeloop"
    write_minimal_root(root)
    monkeypatch.setattr(prepare_cycle, "ROOT", root)

    run_dir = prepare_cycle.prepare("adhoc", "Analyze INFY for a long-only swing setup")

    assert (run_dir / "user_request.md").read_text(encoding="utf-8").endswith("Analyze INFY for a long-only swing setup\n")
    assert (run_dir / "05_adhoc_intake.md").exists()
    assert (run_dir / "orders.json").read_text(encoding="utf-8") == "[]\n"


def test_prepare_adhoc_requires_request(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "tradeloop"
    write_minimal_root(root)
    monkeypatch.setattr(prepare_cycle, "ROOT", root)

    try:
        prepare_cycle.prepare("adhoc", "")
    except ValueError as exc:
        assert "requires --request" in str(exc)
    else:
        raise AssertionError("adhoc prepare should require request text")


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

