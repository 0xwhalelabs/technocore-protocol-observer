#!/usr/bin/env python3
"""Create safe, reproducible snapshots of authoritative Technocore metadata."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


VERSION = "0.1.0"
DEFAULT_BASE_URL = "https://technocore.chat"
DEFAULT_STATE = Path(__file__).with_name("observer-state.json")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
USER_AGENT = f"technocore-protocol-observer/{VERSION}"
PROBES = {
    "manifest": "/.well-known/agent.json",
    "manual": "/llms.txt",
    "openapi": "/openapi.json",
    "health": "/healthz",
    "rooms": "/rooms",
}
ROOMS_PATTERN = re.compile(
    r"^# (?P<listed>\d+) of (?P<rooms>\d+) rooms "
    r"\(cap (?P<room_cap>\d+), (?P<stored>\S+) of (?P<storage_cap>\S+) stored\)"
)
NOTES_PATTERN = re.compile(r"^# notes (?P<notes>\d+) of (?P<note_cap>\d+)")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, path)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("state must contain a JSON object")
    return payload


def fetch_text(
    url: str,
    timeout: float,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "*/*", "User-Agent": USER_AGENT},
    )
    started = time.monotonic()
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            status = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as error:
        return {
            "ok": False,
            "status": error.code,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error": "http_error",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {
            "ok": False,
            "status": None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error": type(error).__name__,
        }
    if len(body) > MAX_RESPONSE_BYTES:
        return {
            "ok": False,
            "status": status,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error": "response_too_large",
        }
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "ok": False,
            "status": status,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error": "invalid_utf8",
        }
    return {
        "ok": True,
        "status": status,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "bytes": len(body),
        "sha256": sha256_text(text),
        "text": text,
    }


def parse_manifest(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("manifest must contain a JSON object")
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    limit_names = (
        "message_chars",
        "note_chars",
        "reads_per_minute_per_ip",
        "writes_per_minute_per_ip",
        "new_rooms_per_day_per_ip",
        "rooms",
        "notes",
        "room_ring_bytes",
        "room_bytes_total",
        "retention_seconds",
        "ephemeral_ttl_seconds",
    )
    return {
        "schema_version": payload.get("schema_version"),
        "name": payload.get("name"),
        "version": payload.get("version"),
        "license": payload.get("license"),
        "limits": {name: limits.get(name) for name in limit_names},
    }


def parse_room_aggregates(text: str) -> dict[str, Any]:
    aggregates: dict[str, Any] = {}
    for line in text.splitlines():
        rooms_match = ROOMS_PATTERN.match(line)
        if rooms_match:
            for name, value in rooms_match.groupdict().items():
                aggregates[name] = int(value) if value.isdigit() else value
        notes_match = NOTES_PATTERN.match(line)
        if notes_match:
            aggregates.update({name: int(value) for name, value in notes_match.groupdict().items()})
    return aggregates


def sanitize_probe(probe: dict[str, Any], kind: str) -> dict[str, Any]:
    public_fields = ("ok", "status", "elapsed_ms", "bytes", "sha256", "error")
    result = {name: probe[name] for name in public_fields if name in probe}
    if not probe.get("ok"):
        return result
    try:
        if kind == "manifest":
            result["metadata"] = parse_manifest(probe["text"])
        elif kind == "rooms":
            result["aggregates"] = parse_room_aggregates(probe["text"])
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        result["ok"] = False
        result["error"] = f"parse_error:{type(error).__name__}"
    return result


def collect_snapshot(base_url: str, timeout: float) -> dict[str, Any]:
    probes: dict[str, Any] = {}
    for name, path in PROBES.items():
        raw = fetch_text(base_url.rstrip("/") + path, timeout)
        probes[name] = sanitize_probe(raw, name)
    return {"observed_utc": utc_now(), "base_url": base_url, "probes": probes}


def protocol_changes(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    before_probes = previous.get("probes") or {}
    after_probes = current.get("probes") or {}
    before_manifest = (before_probes.get("manifest") or {}).get("metadata") or {}
    after_manifest = (after_probes.get("manifest") or {}).get("metadata") or {}
    for field in ("schema_version", "version", "license"):
        before = before_manifest.get(field)
        after = after_manifest.get(field)
        if before is not None and after is not None and before != after:
            changes.append(f"{field} {before}->{after}")
    before_limits = before_manifest.get("limits") or {}
    after_limits = after_manifest.get("limits") or {}
    for name in sorted(set(before_limits) | set(after_limits)):
        before = before_limits.get(name)
        after = after_limits.get(name)
        if before is not None and after is not None and before != after:
            changes.append(f"limit.{name} {before}->{after}")
    for name in ("manual", "openapi"):
        before = (before_probes.get(name) or {}).get("sha256")
        after = (after_probes.get(name) or {}).get("sha256")
        if before and after and before != after:
            changes.append(f"{name} document changed")
    return changes


def availability_changes(
    state: dict[str, Any],
    snapshot: dict[str, Any],
    threshold: int,
) -> list[str]:
    changes: list[str] = []
    failures = state.setdefault("failure_counts", {})
    announced = state.setdefault("announced_down", {})
    for name, probe in snapshot["probes"].items():
        if probe.get("ok"):
            if announced.get(name):
                changes.append(f"{name} recovered")
            failures[name] = 0
            announced[name] = False
            continue
        failures[name] = int(failures.get(name) or 0) + 1
        if failures[name] >= threshold and not announced.get(name):
            changes.append(f"{name} unavailable for {failures[name]} observations")
            announced[name] = True
    return changes


def observe(args: argparse.Namespace) -> dict[str, Any]:
    state = load_state(args.state)
    snapshot = collect_snapshot(args.base_url, args.timeout)
    previous = state.get("last_snapshot")
    changes = protocol_changes(previous, snapshot) if isinstance(previous, dict) else []
    changes.extend(availability_changes(state, snapshot, args.failure_threshold))
    state["last_snapshot"] = snapshot
    state["last_run_utc"] = snapshot["observed_utc"]
    if not previous:
        action = "baseline_saved"
    elif changes:
        action = "change_detected"
    else:
        action = "no_meaningful_change"
    state["last_action"] = action
    atomic_write_json(args.state, state)
    result: dict[str, Any] = {"action": action}
    if action == "baseline_saved":
        result["successful_probes"] = sum(1 for probe in snapshot["probes"].values() if probe.get("ok"))
        result["total_probes"] = len(PROBES)
    elif changes:
        result["changes"] = changes
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--failure-threshold", type=int, default=3)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero")
    if args.failure_threshold < 1:
        raise SystemExit("--failure-threshold must be at least one")
    print(json.dumps(observe(args), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
