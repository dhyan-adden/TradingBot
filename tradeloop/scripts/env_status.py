#!/usr/bin/env python
"""Masked credential status check (Phase 10).

Prints only SET or MISSING for a named environment variable. It never prints
the value, never reads .env, and never greps credentials - the caller (launchd,
a terminal session, or an agent harness) is responsible for injecting the
variable into the environment first.
"""
import os
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: env_status.py VAR_NAME [VAR_NAME ...]", file=sys.stderr)
        return 2
    for name in argv[1:]:
        print(f"{name}={ 'SET' if os.environ.get(name, '').strip() else 'MISSING'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
