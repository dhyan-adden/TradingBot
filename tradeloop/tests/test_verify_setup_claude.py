import subprocess

from tradeloop.scripts import verify_setup


def test_claude_authenticated_true_on_zero_exit(monkeypatch):
    monkeypatch.setattr(verify_setup.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="ok", stderr=""))
    assert verify_setup.claude_authenticated() is True


def test_claude_authenticated_false_on_nonzero(monkeypatch):
    monkeypatch.setattr(verify_setup.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="login"))
    assert verify_setup.claude_authenticated() is False


def test_claude_authenticated_false_on_timeout(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=15)
    monkeypatch.setattr(verify_setup.subprocess, "run", boom)
    assert verify_setup.claude_authenticated() is False


def test_verify_blocks_claude_backend_when_unauthenticated(monkeypatch, capsys):
    monkeypatch.setattr(verify_setup, "claude_authenticated", lambda *a, **k: False)
    rc = verify_setup.verify("premarket", backend="claude")
    assert rc == 4
    assert "CLAUDE_AUTH_MISSING" in capsys.readouterr().out


def test_verify_ignores_claude_auth_for_openrouter(monkeypatch, capsys):
    monkeypatch.setattr(verify_setup, "claude_authenticated", lambda *a, **k: False)
    rc = verify_setup.verify("premarket", backend="openrouter")
    assert rc == 0
    assert "tradeloop_setup=OK" in capsys.readouterr().out
