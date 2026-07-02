from datetime import datetime, timezone


def log_line(scope: str, message: str) -> str:
    return f"[{datetime.now(timezone.utc).isoformat()}] {scope}: {message}"

