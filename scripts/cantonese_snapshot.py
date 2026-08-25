#!/usr/bin/env python3
"""Capture and read one immutable Cantonese publication snapshot per run.

The Japanese edition must never mix files fetched from different Cantonese
commits. capture() resolves Cantonese main to one commit SHA, downloads every
required JSON file from that SHA, and stores them under CANTONESE_SNAPSHOT_DIR.
All downstream translation/parity steps then read only these local files.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

REPO = "kanuli/daily-brief-newspaper"
API_COMMIT = f"https://api.github.com/repos/{REPO}/commits/main"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}"
DEFAULT_DIR = ".cantonese-snapshot/data"
BASE_FILES = (
    "latest.json",
    "live.json",
    "archive.json",
    "desk-latest.json",
    "stocks-latest.json",
)


def snapshot_dir() -> Path:
    return Path(os.environ.get("CANTONESE_SNAPSHOT_DIR", DEFAULT_DIR))


def _get_json(url: str, optional: bool = False):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "daily-brief-newspaper-japanese-snapshot"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if optional and exc.code == 404:
            return None
        raise


def resolve_commit() -> str:
    payload = _get_json(API_COMMIT)
    sha = str((payload or {}).get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError(f"Could not resolve immutable Cantonese commit: {sha!r}")
    return sha


def _write(name: str, payload) -> None:
    path = snapshot_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def capture() -> str:
    root = snapshot_dir()
    root.mkdir(parents=True, exist_ok=True)
    sha = resolve_commit()

    latest = _get_json(f"{RAW_BASE}/{sha}/data/latest.json")
    _write("latest.json", latest)
    date = str((latest or {}).get("date") or "")

    for name in BASE_FILES[1:]:
        payload = _get_json(f"{RAW_BASE}/{sha}/data/{name}")
        _write(name, payload)

    optional_files = []
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        optional_files.append(f"topic-more/{date}.json")
    for name in optional_files:
        payload = _get_json(f"{RAW_BASE}/{sha}/data/{name}", optional=True)
        if payload is not None:
            _write(name, payload)

    meta = {
        "repository": REPO,
        "commit": sha,
        "date": date,
        "files": [*BASE_FILES, *optional_files],
    }
    (root.parent / "snapshot-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "CANTONESE_SNAPSHOT_OK",
        f"commit={sha}",
        f"date={date}",
        f"dir={root}",
    )
    return sha


def load_json(name: str, optional: bool = False):
    path = snapshot_dir() / name
    if not path.is_file():
        if optional:
            return None
        raise FileNotFoundError(f"Cantonese snapshot file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_commit() -> str:
    path = snapshot_dir().parent / "snapshot-meta.json"
    if not path.is_file():
        return ""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("commit") or "")
    except Exception:
        return ""


if __name__ == "__main__":
    capture()
