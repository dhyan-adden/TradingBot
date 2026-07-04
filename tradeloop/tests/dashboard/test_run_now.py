from pathlib import Path

from tradeloop.dashboard.server import launch_propose


def test_launch_propose_invokes_claude_backend_with_data_on():
    captured = {}

    def fake_launcher(cmd, env=None, **kw):
        captured["cmd"] = cmd
        captured["env"] = env
        return object()

    launch_propose(Path("/tmp/x"), python="python3", launcher=fake_launcher)
    cmd = captured["cmd"]
    assert "tradeloop.orchestrator" in " ".join(cmd)
    assert "premarket" in cmd
    assert "--backend" in cmd and "claude" in cmd
    assert captured["env"]["ZERODHA_ENABLE_DATA"] == "true"
    # must NOT enable live trading
    assert captured["env"].get("ZERODHA_ENABLE_TRADING", "false") != "true"
