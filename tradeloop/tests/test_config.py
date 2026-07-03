from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_settings_yaml_has_phase0_knobs() -> None:
    data = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    assert data["capital"]["max_total_deployed_pct"] == 90
    assert data["cycle_timeout_seconds"] == 1200
