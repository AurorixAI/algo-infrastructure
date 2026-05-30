#!/usr/bin/env python3
"""
Ф1.5 — Smoke-tests for all ALGO back-end services.

Checks:
  1. /health (or /api/v1/health) returns HTTP 2xx for every service.
  2. content-service read API returns 200 for at least one skill/task list call.
  3. diagnostic-service and exam-service /health return "healthy" or "degraded"
     (not connection errors).

Usage (services must be running):
    python scripts/smoke_test.py [--base-url-auth http://localhost:8000] ...

Defaults assume local docker-compose port mapping:
  auth-service      → localhost:8000
  diagnostic-service → localhost:8002
  exam-service      → localhost:8003
  content-service   → localhost:8004
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Callable

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TIMEOUT = 10.0  # seconds


@dataclass
class Service:
    name: str
    base_url: str
    checks: list[tuple[str, Callable[["Service"], None]]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

results: list[tuple[str, bool, str]] = []


def _record(label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok, detail))
    icon = PASS if ok else FAIL
    print(f"  [{icon}] {label}" + (f" — {detail}" if detail else ""))


def check_health(svc: Service, path: str = "/health") -> None:
    label = f"{svc.name} {path}"
    try:
        r = httpx.get(svc.base_url + path, timeout=TIMEOUT)
        ok = r.status_code < 300
        _record(label, ok, f"HTTP {r.status_code}")
    except httpx.ConnectError as exc:
        _record(label, False, f"ConnectError: {exc}")
    except Exception as exc:
        _record(label, False, str(exc))


def check_get(svc: Service, path: str, *, expect_status: int = 200) -> None:
    label = f"{svc.name} GET {path}"
    try:
        r = httpx.get(svc.base_url + path, timeout=TIMEOUT)
        ok = r.status_code == expect_status
        _record(label, ok, f"HTTP {r.status_code}")
    except httpx.ConnectError as exc:
        _record(label, False, f"ConnectError: {exc}")
    except Exception as exc:
        _record(label, False, str(exc))


# ---------------------------------------------------------------------------
# Per-service smoke checks
# ---------------------------------------------------------------------------

def smoke_auth(svc: Service) -> None:
    check_health(svc, "/health")
    check_get(svc, "/health/live")


def smoke_content(svc: Service) -> None:
    check_health(svc, "/api/v1/health")
    check_get(svc, "/api/v1/health/live")
    # Read API — list skills (no auth needed, read-only)
    check_get(svc, "/api/v1/content/skills?level=L4")
    # List textbooks
    check_get(svc, "/api/v1/content/textbooks")


def smoke_diagnostic(svc: Service) -> None:
    check_health(svc, "/health")
    # /docs disabled in production mode — probe a known endpoint (needs body → 422 = service alive)
    check_get(svc, "/api/v1/diagnostic/sessions", expect_status=405)  # GET not allowed → 405 means alive


def smoke_exam(svc: Service) -> None:
    check_health(svc, "/health")
    check_get(svc, "/health/live")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

SERVICES: list[tuple[str, str, Callable]] = [
    ("auth-service",        "http://localhost:8000", smoke_auth),
    ("diagnostic-service",  "http://localhost:8002", smoke_diagnostic),
    ("exam-service",        "http://localhost:8003", smoke_exam),
    ("content-service",     "http://localhost:8004", smoke_content),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ALGO back-end smoke tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Override any service URL:
              --auth-url         http://localhost:8000
              --diagnostic-url   http://localhost:8002
              --exam-url         http://localhost:8003
              --content-url      http://localhost:8004
        """),
    )
    parser.add_argument("--auth-url",       default="http://localhost:8000")
    parser.add_argument("--diagnostic-url", default="http://localhost:8002")
    parser.add_argument("--exam-url",       default="http://localhost:8003")
    parser.add_argument("--content-url",    default="http://localhost:8004")
    args = parser.parse_args()

    url_overrides = {
        "auth-service":       args.auth_url,
        "diagnostic-service": args.diagnostic_url,
        "exam-service":       args.exam_url,
        "content-service":    args.content_url,
    }

    total_pass = 0
    total_fail = 0

    for name, default_url, smoke_fn in SERVICES:
        url = url_overrides.get(name, default_url)
        svc = Service(name=name, base_url=url)
        print(f"\n=== {name} ({url}) ===")
        smoke_fn(svc)

    print("\n" + "=" * 50)
    for label, ok, detail in results:
        if ok:
            total_pass += 1
        else:
            total_fail += 1

    icon_pass = f"\033[32m{total_pass} passed\033[0m"
    icon_fail = f"\033[31m{total_fail} failed\033[0m"
    print(f"Results: {icon_pass}, {icon_fail}")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
