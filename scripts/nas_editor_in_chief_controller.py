#!/usr/bin/env python3
"""NAS-owned controller for the Japanese news delivery chain.

The NAS runs this script on its existing Editor-in-Chief schedule. GitHub
workflows have no newsroom cron ownership: the NAS dispatches translation or a
repair, GitHub chains successful translation to F3 and successful F3 to Pages,
and the NAS is the only component allowed to attest final GREEN health.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


REPOSITORY = os.getenv("JAPANESE_GITHUB_REPOSITORY", "kanuli/daily-brief-newspaper-japanese")
TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
API = f"https://api.github.com/repos/{REPOSITORY}"
UPSTREAM = os.getenv(
    "CANTONESE_RAW_BASE",
    "https://raw.githubusercontent.com/kanuli/daily-brief-newspaper/main/data/",
).rstrip("/") + "/"
JAPANESE = os.getenv(
    "JAPANESE_RAW_BASE",
    "https://raw.githubusercontent.com/kanuli/daily-brief-newspaper-japanese/main/data/",
).rstrip("/") + "/"
PAGES = os.getenv(
    "JAPANESE_PAGES_BASE",
    "https://kanuli.github.io/daily-brief-newspaper-japanese/",
).rstrip("/") + "/"

LAYERS = ("latest.json", "live.json", "desk-latest.json", "stocks-latest.json")
F3_WORKFLOW = "rebuild-f3-pacing.yml"
PAGES_WORKFLOW = "pages.yml"
ATTEST_WORKFLOW = "editor-in-chief-newsroom-robot.yml"


def request(url: str, *, method: str = "GET", payload: dict | None = None) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
        "User-Agent": "nas-japanese-editor-in-chief",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {TOKEN}"
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def load_json(base: str, name: str) -> dict:
    joiner = "&" if "?" in name else "?"
    raw = request(urllib.parse.urljoin(base, name) + f"{joiner}nas_verify={time.time_ns()}")
    return json.loads(raw.decode("utf-8"))


def parse_stamp(payload: dict) -> datetime | None:
    for key in ("generatedAt", "lastUpdated", "sourceGeneratedAt", "checkedAt"):
        value = payload.get(key)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def iso_millis(value: datetime | None) -> str:
    if value is None:
        return "missing"
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def publication_fingerprint(layers: dict[str, dict]) -> str:
    daily = str(layers["latest.json"].get("date") or "")[:10] or "missing"
    return "|".join(
        (
            daily,
            iso_millis(parse_stamp(layers["live.json"])),
            iso_millis(parse_stamp(layers["desk-latest.json"])),
            iso_millis(parse_stamp(layers["stocks-latest.json"])),
        )
    )


def current(source: dict, japanese: dict, tolerance_seconds: int) -> bool:
    source_stamp = parse_stamp(source)
    japanese_stamp = parse_stamp(japanese)
    return bool(source_stamp and japanese_stamp and japanese_stamp.timestamp() + tolerance_seconds >= source_stamp.timestamp())


def workflow_runs(workflow: str) -> list[dict]:
    data = json.loads(request(f"{API}/actions/workflows/{workflow}/runs?branch=main&per_page=20"))
    return list(data.get("workflow_runs") or [])


def dispatch(workflow: str, inputs: dict | None = None) -> bool:
    active = next((run for run in workflow_runs(workflow) if run.get("status") != "completed"), None)
    if active:
        print(f"NAS_DISPATCH_SKIPPED_ACTIVE workflow={workflow} run={active.get('id')}")
        return False
    payload = {"ref": "main"}
    if inputs:
        payload["inputs"] = inputs
    request(f"{API}/actions/workflows/{workflow}/dispatches", method="POST", payload=payload)
    print(f"NAS_DISPATCHED workflow={workflow}")
    return True


def iter_stories(payload: object):
    if isinstance(payload, dict):
        if payload.get("id") and (payload.get("title") or payload.get("body") or payload.get("summary")):
            yield payload
        for value in payload.values():
            yield from iter_stories(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from iter_stories(value)


def verify_pages_assets(layers: dict[str, dict]) -> list[str]:
    failures: list[str] = []
    for name, expected in layers.items():
        published = load_json(PAGES + "data/", name)
        if name == "latest.json":
            if str(published.get("date") or "")[:10] < str(expected.get("date") or "")[:10]:
                failures.append(f"pages:{name}:stale")
        elif not current(expected, published, 0):
            failures.append(f"pages:{name}:stale")

    seen: set[tuple[str, str]] = set()
    for payload in layers.values():
        for story in iter_stories(payload):
            audio = str(story.get("audio") or "")
            timing = str(story.get("timing") or "")
            if not audio or not timing:
                failures.append(f"f3:{story.get('id')}:missing-audio-metadata")
                continue
            if (audio, timing) in seen:
                continue
            seen.add((audio, timing))
            try:
                request(urllib.parse.urljoin(PAGES, audio) + f"?nas_audio={time.time_ns()}")
                timing_data = json.loads(
                    request(urllib.parse.urljoin(PAGES, timing) + f"?nas_timing={time.time_ns()}").decode("utf-8")
                )
                if timing_data.get("deliveryProfile") != "jp-tv-news-semantic-v4":
                    failures.append(f"f3:{story.get('id')}:wrong-profile")
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                failures.append(f"f3:{story.get('id')}:{type(exc).__name__}")
    return failures


def main() -> int:
    if not TOKEN:
        print("NAS_CONTROLLER_RED GITHUB_TOKEN is required for workflow dispatch", file=sys.stderr)
        return 2

    upstream = {name: load_json(UPSTREAM, name) for name in LAYERS}
    japanese = {name: load_json(JAPANESE, name) for name in LAYERS}

    core_stale = (
        str(japanese["latest.json"].get("date") or "")[:10]
        < str(upstream["latest.json"].get("date") or "")[:10]
        or not current(upstream["live.json"], japanese["live.json"], 60)
    )
    rolling_stale = (
        not current(upstream["desk-latest.json"], japanese["desk-latest.json"], 3600)
        or not current(upstream["stocks-latest.json"], japanese["stocks-latest.json"], 3600)
    )
    if core_stale:
        dispatch("sync-japanese-news.yml")
    if rolling_stale:
        dispatch("repair-extra-translation-quality.yml")
    if core_stale or rolling_stale:
        print(f"NAS_CONTROLLER_RED core_stale={core_stale} rolling_stale={rolling_stale}")
        return 1

    failures = verify_pages_assets(japanese)
    if failures:
        audio_failures = [failure for failure in failures if failure.startswith("f3:")]
        if audio_failures:
            dispatch(F3_WORKFLOW)
        else:
            dispatch(PAGES_WORKFLOW)
        print("NAS_CONTROLLER_RED " + " | ".join(failures[:20]))
        return 1

    fingerprint = publication_fingerprint(japanese)
    verified_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    dispatch(
        ATTEST_WORKFLOW,
        {"nas_verified_fingerprint": fingerprint, "nas_verified_at": verified_at},
    )
    print(f"NAS_CONTROLLER_GREEN fingerprint={fingerprint} verified_at={verified_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
