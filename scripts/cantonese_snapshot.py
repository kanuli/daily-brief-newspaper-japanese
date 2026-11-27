#!/usr/bin/env python3
"""Capture and read one immutable Cantonese publication snapshot per run.

The Japanese edition must never mix files fetched from different Cantonese
commits. capture() resolves Cantonese main to one commit SHA, downloads every
required JSON file from that SHA, and stores them under CANTONESE_SNAPSHOT_DIR.
All downstream translation/parity steps then read only these local files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = "kanuli/daily-brief-newspaper"
GIT_REMOTE = f"https://github.com/{REPO}.git"
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


def _get_bytes(url: str, optional: bool = False):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "daily-brief-newspaper-japanese-snapshot"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(33554433)
            if response.geturl() != url or not 0 < len(data) <= 33554432:
                raise ValueError("Invalid source snapshot response")
            json.loads(data)
            return data
    except urllib.error.HTTPError as exc:
        if optional and exc.code == 404:
            return None
        raise


def resolve_commit() -> str:
    """Resolve public Cantonese main without consuming GitHub REST API quota."""
    result = subprocess.run(
        ["git", "ls-remote", GIT_REMOTE, "refs/heads/main"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    first = (result.stdout or "").strip().splitlines()
    sha = first[0].split()[0] if first else ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError(f"Could not resolve immutable Cantonese commit: {sha!r}")
    print("CANTONESE_SNAPSHOT_RESOLVED_BY_GIT", sha)
    return sha


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        stage = Path(temp.name)
        try:
            temp.write(raw)
            temp.flush()
            os.fsync(temp.fileno())
            os.replace(stage, path)
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            stage.unlink(missing_ok=True)


def read_remote(revision, name, optional=False):
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or not (
            name in BASE_FILES or re.fullmatch(r"topic-more/\d{4}-\d{2}-\d{2}\.json",name)):
        raise ValueError("Invalid Cantonese snapshot path or revision")
    return _get_bytes(f"{RAW_BASE}/{revision}/data/{name}", optional=optional)


def capture() -> str:
    root = snapshot_dir()
    revision = resolve_commit()
    files = {name: read_remote(revision,name) for name in BASE_FILES}
    date = str(json.loads(files["latest.json"]).get("date") or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        name = f"topic-more/{date}.json"
        extra = read_remote(revision,name,optional=True)
        if extra is not None:
            files[name] = extra

    for name, raw in files.items():
        write_atomic(root/name, raw)
    # A reader that sees any interrupted replacement fails its hash check.
    manifest = {"repository":REPO, "commit":revision, "date":date,
                "files":sorted(files), "sha256":{name:sha(raw) for name,raw in files.items()}}
    write_atomic(root.parent/"snapshot-meta.json", json.dumps(manifest,sort_keys=True).encode()+b"\n")
    print("CANTONESE_SNAPSHOT_OK",f"commit={revision}",f"date={date}",f"dir={root}")
    return revision


def metadata():
    result = json.loads((snapshot_dir().parent/"snapshot-meta.json").read_bytes())
    if (result["repository"] != REPO or not re.fullmatch(r"[0-9a-f]{40}",result["commit"])
            or set(result["files"]) != set(result["sha256"]) or not set(BASE_FILES)<=set(result["files"])):
        raise ValueError("Invalid snapshot manifest")
    return result


def load_bytes(name, optional=False, *, manifest=None):
    manifest = metadata() if manifest is None else manifest
    expected=manifest["sha256"].get(name)
    if expected is None:
        if optional:
            return None
        raise FileNotFoundError(f"Cantonese snapshot file missing: {name}")
    if not (name in BASE_FILES or re.fullmatch(r"topic-more/\d{4}-\d{2}-\d{2}\.json",name)):
        raise ValueError("Invalid snapshot path")
    raw = (snapshot_dir()/name).read_bytes()
    if sha(raw)!=expected or manifest != metadata():
        raise ValueError("Cantonese snapshot changed during read")
    return raw


def load_json(name: str, optional: bool = False):
    raw = load_bytes(name,optional=optional)
    return None if raw is None else json.loads(raw)


def snapshot_commit() -> str:
    try:
        return metadata()["commit"]
    except (OSError, KeyError, ValueError):
        return ""


if __name__ == "__main__":
    capture()
