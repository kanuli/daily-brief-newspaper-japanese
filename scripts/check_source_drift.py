#!/usr/bin/env python3
"""Verify that Japanese publication data is derived from the current Cantonese source.

This does not compare translated text. It verifies source fingerprints so the
Japanese edition cannot silently use an independent, truncated, or stale story
set.
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import validate_content_integrity as integrity

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BASE = "https://raw.githubusercontent.com/kanuli/daily-brief-newspaper/main/data"
BASE_FILES = ("latest.json", "live.json", "archive.json")
EXTRA_FILES = ("desk-latest.json", "stocks-latest.json")


def fingerprint(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def remote_json(name, optional=False):
    req = urllib.request.Request(
        f"{SOURCE_BASE}/{name}",
        headers={"User-Agent": "daily-brief-newspaper-japanese-source-parity"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if optional and exc.code == 404:
            return None
        raise


def local_json(name):
    path = ROOT / "data" / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def emit(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{key}={value}\n")


def current_date():
    latest = local_json("latest.json") or {}
    value = str(latest.get("date") or "")
    return value if len(value) == 10 else ""


def verify_fingerprint(name, optional=False):
    source = remote_json(name, optional=optional)
    if source is None:
        return None, None
    local = local_json(name)
    expected = fingerprint(source)
    actual = str((local or {}).get("sourceFingerprint") or "")
    return expected, actual


def main():
    drift = []
    errors = []
    integrity_bad = []

    for name in BASE_FILES:
        try:
            expected, actual = verify_fingerprint(name)
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}")
            continue
        local = local_json(name)
        if expected != actual:
            drift.append(name)
        if local is None:
            integrity_bad.append(name)
        else:
            issues = integrity.collect_issues(name, local)
            if issues:
                integrity_bad.append(name)

    extra_names = list(EXTRA_FILES)
    date = current_date()
    if date:
        extra_names.append(f"topic-more/{date}.json")

    for name in extra_names:
        optional = name.startswith("topic-more/")
        try:
            expected, actual = verify_fingerprint(name, optional=optional)
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}")
            continue
        if expected is None:
            # Optional source absent: local copy should also be absent.
            if local_json(name) is not None:
                drift.append(name)
            continue
        if expected != actual:
            drift.append(name)

    dirty = sorted(set(drift) | set(integrity_bad))
    available = not errors
    emit("available", str(available).lower())
    emit("drift", str(bool(dirty)).lower())
    emit("files", ",".join(dirty))
    emit("integrity", ",".join(sorted(set(integrity_bad))))
    emit("errors", ",".join(errors))

    if errors:
        print("SOURCE_PARITY_CHECK_DEGRADED", ",".join(errors))
    if integrity_bad:
        print("LOCAL_CONTENT_INTEGRITY_FAIL", ",".join(sorted(set(integrity_bad))))
    if dirty:
        print("CANTONESE_SOURCE_PARITY_FAIL", ",".join(dirty))
        return 10

    print("CANTONESE_SOURCE_PARITY_OK" if available else "CANTONESE_SOURCE_PARITY_UNKNOWN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
