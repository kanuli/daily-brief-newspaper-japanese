#!/usr/bin/env python3
"""NAS-owned Editor-in-Chief control plane for the Japanese newsroom.

The Editor-in-Chief is the only scheduler/orchestrator. GitHub Actions are
specialist robots: they execute one bounded job and return. The controller
serializes publication writers, verifies each stage, chooses an alternate
recovery robot when available, and only attests GREEN after deployed Pages and
F3 assets match the current Japanese newsroom state.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Set, Tuple


REPOSITORY = os.getenv("JAPANESE_GITHUB_REPOSITORY", "kanuli/daily-brief-newspaper-japanese")
TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
API = f"https://api.github.com/repos/{REPOSITORY}"
UPSTREAM = os.getenv(
    "CANTONESE_RAW_BASE",
    "https://raw.githubusercontent.com/kanuli/daily-brief-newspaper/main/data/",
).rstrip("/") + "/"
JAPANESE_ROOT = os.getenv(
    "JAPANESE_RAW_ROOT",
    "https://raw.githubusercontent.com/kanuli/daily-brief-newspaper-japanese/main/",
).rstrip("/") + "/"
JAPANESE = os.getenv("JAPANESE_RAW_BASE", JAPANESE_ROOT + "data/").rstrip("/") + "/"
PAGES = os.getenv(
    "JAPANESE_PAGES_BASE",
    "https://kanuli.github.io/daily-brief-newspaper-japanese/",
).rstrip("/") + "/"
STATE_PATH = Path(
    os.getenv(
        "EDITOR_STATE_PATH",
        "/volume2/docker/editor-in-chief/state/japanese-newsroom-control-plane.json",
    )
)

LAYERS = ("latest.json", "live.json", "desk-latest.json", "stocks-latest.json")
ROBOTS = {
    "core-translator": "sync-japanese-news.yml",
    "core-exhaustive-recovery": "recover-core-news.yml",
    "rolling-translator": "repair-extra-translation-quality.yml",
    "rolling-exhaustive-recovery": "repair-all-published-quality.yml",
    "vocab-translator": "sync-daily-vocab.yml",
    "vocab-exhaustive-recovery": "recover-daily-vocab.yml",
    "f3-voice": "rebuild-f3-pacing.yml",
    "pages-publisher": "pages.yml",
    "delivery-auditor": "editor-in-chief-newsroom-robot.yml",
}
MUTATING_ROBOTS = (
    "core-translator",
    "core-exhaustive-recovery",
    "rolling-translator",
    "rolling-exhaustive-recovery",
    "vocab-translator",
    "vocab-exhaustive-recovery",
    "f3-voice",
)
STOCK_MAX_AGE_SECONDS = max(3600, int(os.getenv("STOCK_MAX_AGE_SECONDS", str(6 * 3600))))
HKT = timezone(timedelta(hours=8))


def request(url: str, *, method: str = "GET", payload: Optional[dict] = None) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
        "User-Agent": "nas-japanese-editor-in-chief-v2",
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


def parse_stamp(payload: dict) -> Optional[datetime]:
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


def iso_millis(value: Optional[datetime]) -> str:
    if value is None:
        return "missing"
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def publication_fingerprint(layers: Dict[str, dict], vocab: Optional[dict] = None) -> str:
    daily = str(layers["latest.json"].get("date") or "")[:10] or "missing"
    vocab_day = str((vocab or {}).get("date") or "")[:10] or "missing"
    return "|".join(
        (
            daily,
            iso_millis(parse_stamp(layers["live.json"])),
            iso_millis(parse_stamp(layers["desk-latest.json"])),
            iso_millis(parse_stamp(layers["stocks-latest.json"])),
            vocab_day,
        )
    )


def current(source: dict, japanese: dict, tolerance_seconds: int) -> bool:
    source_stamp = parse_stamp(source)
    japanese_stamp = parse_stamp(japanese)
    return bool(source_stamp and japanese_stamp and japanese_stamp.timestamp() + tolerance_seconds >= source_stamp.timestamp())


def absolute_fresh(payload: dict, max_age_seconds: int) -> bool:
    stamp = parse_stamp(payload)
    if stamp is None:
        return False
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    return 0 <= age <= max_age_seconds


def hkt_today() -> str:
    return datetime.now(HKT).date().isoformat()


def translation_reasons(label: str, payload: dict) -> list:
    reasons = []
    if bool(payload.get("translationDegraded")):
        reasons.append(f"{label}:translationDegraded=true")
    deferred = int(payload.get("translationDeferredCount") or 0)
    if deferred > 0:
        reasons.append(f"{label}:translationDeferredCount={deferred}")
    bad = {"EDITORIAL_MINIMUM_FALLBACK", "TRANSLATION_FAILED", "TRANSLATION_DEGRADED"}
    for story in iter_stories(payload):
        status = str(story.get("translationStatus") or "").strip().upper()
        if status in bad:
            reasons.append(f"{label}:{story.get('id')}:translationStatus={status}")
            if len(reasons) >= 12:
                break
    return reasons


def workflow_runs(workflow: str) -> list:
    data = json.loads(request(f"{API}/actions/workflows/{workflow}/runs?branch=main&per_page=20"))
    return list(data.get("workflow_runs") or [])


def active_run(workflow: str) -> Optional[dict]:
    return next((run for run in workflow_runs(workflow) if run.get("status") != "completed"), None)


def latest_completed_run(workflow: str) -> Optional[dict]:
    return next((run for run in workflow_runs(workflow) if run.get("status") == "completed"), None)


def any_mutating_robot_active() -> Optional[Tuple[str, dict]]:
    for robot in MUTATING_ROBOTS:
        run = active_run(ROBOTS[robot])
        if run:
            return robot, run
    return None


def dispatch_robot(robot: str, *, reason: str, inputs: Optional[dict] = None, serialize_writers: bool = False) -> bool:
    workflow = ROBOTS[robot]
    own_active = active_run(workflow)
    if own_active:
        print(f"EDITOR_JOB_WAIT robot={robot} workflow={workflow} run={own_active.get('id')} reason={reason}")
        return False
    if serialize_writers:
        blocker = any_mutating_robot_active()
        if blocker:
            blocker_robot, blocker_run = blocker
            print(
                "EDITOR_JOB_BLOCKED_BY_WRITER "
                f"robot={robot} blocker={blocker_robot} run={blocker_run.get('id')} reason={reason}"
            )
            return False
    payload = {"ref": "main"}
    if inputs:
        payload["inputs"] = inputs
    request(f"{API}/actions/workflows/{workflow}/dispatches", method="POST", payload=payload)
    print(f"EDITOR_JOB_ASSIGNED robot={robot} workflow={workflow} reason={reason}")
    return True


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 2, "jobs": {}, "updatedAt": None}


def save_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state["version"] = 2
        state["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        temp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(STATE_PATH)
    except OSError as exc:
        print(f"EDITOR_STATE_WARNING path={STATE_PATH} error={exc}", file=sys.stderr)


def mark_job(state: dict, job: str, status: str, *, reason: str, robot: Optional[str] = None) -> None:
    state.setdefault("jobs", {})[job] = {
        "status": status,
        "robot": robot,
        "reason": reason,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    save_state(state)


def iter_stories(payload: object):
    if isinstance(payload, dict):
        if payload.get("id") and (payload.get("title") or payload.get("body") or payload.get("summary")):
            yield payload
        for value in payload.values():
            yield from iter_stories(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from iter_stories(value)


def degraded_translation(payload: dict) -> bool:
    """Fallback/minimum cards are not a healthy translated newsroom layer."""
    if bool(payload.get("translationDegraded")):
        return True
    if int(payload.get("translationDeferredCount") or 0) > 0:
        return True
    for story in iter_stories(payload):
        status = str(story.get("translationStatus") or "").strip().upper()
        if status in {"EDITORIAL_MINIMUM_FALLBACK", "TRANSLATION_FAILED", "TRANSLATION_DEGRADED"}:
            return True
    return False


def verify_main_f3(layers: Dict[str, dict]) -> list:
    """Verify current main has complete F3 metadata/assets before publication."""
    failures = []
    if vocab is not None:
        try:
            published_vocab = load_json(PAGES + "data/", "vocab/latest.json")
            expected_day = str(vocab.get("date") or "")[:10]
            published_day = str(published_vocab.get("date") or "")[:10]
            if published_day != expected_day:
                failures.append(f"pages:vocab/latest.json:stale:{published_day}!={expected_day}")
            dated_day = today or expected_day
            if dated_day:
                published_archive = load_json(PAGES + "data/", f"vocab/{dated_day}.json")
                if str(published_archive.get("date") or "")[:10] != dated_day:
                    failures.append(f"pages:vocab/{dated_day}.json:invalid")
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            failures.append(f"pages:vocab:{type(exc).__name__}")

    seen = set()  # type: Set[Tuple[str, str]]
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
                request(urllib.parse.urljoin(JAPANESE_ROOT, audio) + f"?nas_main_audio={time.time_ns()}")
                timing_data = json.loads(
                    request(urllib.parse.urljoin(JAPANESE_ROOT, timing) + f"?nas_main_timing={time.time_ns()}").decode("utf-8")
                )
                if timing_data.get("deliveryProfile") != "jp-tv-news-semantic-v4":
                    failures.append(f"f3:{story.get('id')}:wrong-profile")
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                failures.append(f"f3:{story.get('id')}:{type(exc).__name__}")
    return failures


def verify_pages(layers: Dict[str, dict], vocab: Optional[dict] = None, today: Optional[str] = None) -> list:
    """Verify deployed Pages matches main after content, vocab and F3 are complete."""
    failures = []
    for name, expected in layers.items():
        try:
            published = load_json(PAGES + "data/", name)
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            failures.append(f"pages:{name}:{type(exc).__name__}")
            continue
        if name == "latest.json":
            if str(published.get("date") or "")[:10] < str(expected.get("date") or "")[:10]:
                failures.append(f"pages:{name}:stale")
        elif not current(expected, published, 0):
            failures.append(f"pages:{name}:stale")
        if degraded_translation(published):
            failures.append(f"pages:{name}:degraded-translation")

    seen = set()  # type: Set[Tuple[str, str]]
    for payload in layers.values():
        for story in iter_stories(payload):
            audio = str(story.get("audio") or "")
            timing = str(story.get("timing") or "")
            if not audio or not timing or (audio, timing) in seen:
                continue
            seen.add((audio, timing))
            try:
                request(urllib.parse.urljoin(PAGES, audio) + f"?nas_page_audio={time.time_ns()}")
                timing_data = json.loads(
                    request(urllib.parse.urljoin(PAGES, timing) + f"?nas_page_timing={time.time_ns()}").decode("utf-8")
                )
                if timing_data.get("deliveryProfile") != "jp-tv-news-semantic-v4":
                    failures.append(f"pages-f3:{story.get('id')}:wrong-profile")
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                failures.append(f"pages-f3:{story.get('id')}:{type(exc).__name__}")
    return failures


def choose_alternate_robot(primary: str, fallback: str) -> str:
    """Alternate after a completed attempt; verification, not workflow success, is authoritative."""
    primary_run = latest_completed_run(ROBOTS[primary])
    fallback_run = latest_completed_run(ROBOTS[fallback])
    if primary_run is None:
        return primary
    if fallback_run is None:
        return fallback
    primary_at = str(primary_run.get("updated_at") or primary_run.get("created_at") or "")
    fallback_at = str(fallback_run.get("updated_at") or fallback_run.get("created_at") or "")
    return fallback if primary_at >= fallback_at else primary


def choose_core_robot() -> str:
    return choose_alternate_robot("core-translator", "core-exhaustive-recovery")


def choose_rolling_robot() -> str:
    return choose_alternate_robot("rolling-translator", "rolling-exhaustive-recovery")


def choose_vocab_robot() -> str:
    return choose_alternate_robot("vocab-translator", "vocab-exhaustive-recovery")


def main() -> int:
    if not TOKEN:
        print("NAS_CONTROLLER_RED GITHUB_TOKEN is required for workflow dispatch", file=sys.stderr)
        return 2

    state = load_state()
    upstream = {name: load_json(UPSTREAM, name) for name in LAYERS}
    japanese = {name: load_json(JAPANESE, name) for name in LAYERS}
    upstream_vocab = load_json(UPSTREAM, "vocab/latest.json")
    japanese_vocab = load_json(JAPANESE, "vocab/latest.json")
    today = hkt_today()

    core_reasons = []
    upstream_daily = str(upstream["latest.json"].get("date") or "")[:10]
    japanese_daily = str(japanese["latest.json"].get("date") or "")[:10]
    if japanese_daily < upstream_daily:
        core_reasons.append(f"latest-date-stale:upstream={upstream_daily}:japanese={japanese_daily}")
    if not current(upstream["live.json"], japanese["live.json"], 60):
        core_reasons.append(
            "live-stale:"
            f"upstream={iso_millis(parse_stamp(upstream['live.json']))}:"
            f"japanese={iso_millis(parse_stamp(japanese['live.json']))}"
        )
    core_reasons.extend(translation_reasons("latest.json", japanese["latest.json"]))
    core_reasons.extend(translation_reasons("live.json", japanese["live.json"]))

    rolling_reasons = []
    if not current(upstream["desk-latest.json"], japanese["desk-latest.json"], 60):
        rolling_reasons.append(
            "desk-stale:"
            f"upstream={iso_millis(parse_stamp(upstream['desk-latest.json']))}:"
            f"japanese={iso_millis(parse_stamp(japanese['desk-latest.json']))}"
        )
    if not current(upstream["stocks-latest.json"], japanese["stocks-latest.json"], 60):
        rolling_reasons.append(
            "stocks-relative-stale:"
            f"upstream={iso_millis(parse_stamp(upstream['stocks-latest.json']))}:"
            f"japanese={iso_millis(parse_stamp(japanese['stocks-latest.json']))}"
        )
    if not absolute_fresh(upstream["stocks-latest.json"], STOCK_MAX_AGE_SECONDS):
        rolling_reasons.append(
            "stocks-upstream-absolute-stale:"
            f"stamp={iso_millis(parse_stamp(upstream['stocks-latest.json']))}:"
            f"maxAgeSeconds={STOCK_MAX_AGE_SECONDS}"
        )
    if not absolute_fresh(japanese["stocks-latest.json"], STOCK_MAX_AGE_SECONDS):
        rolling_reasons.append(
            "stocks-japanese-absolute-stale:"
            f"stamp={iso_millis(parse_stamp(japanese['stocks-latest.json']))}:"
            f"maxAgeSeconds={STOCK_MAX_AGE_SECONDS}"
        )
    rolling_reasons.extend(translation_reasons("desk-latest.json", japanese["desk-latest.json"]))
    rolling_reasons.extend(translation_reasons("stocks-latest.json", japanese["stocks-latest.json"]))

    vocab_reasons = []
    upstream_vocab_day = str(upstream_vocab.get("date") or "")[:10]
    japanese_vocab_day = str(japanese_vocab.get("date") or "")[:10]
    if upstream_vocab_day != today:
        vocab_reasons.append(f"vocab-upstream-date-not-today:expected={today}:actual={upstream_vocab_day}")
    if japanese_vocab_day != today:
        vocab_reasons.append(f"vocab-latest-date-not-today:expected={today}:actual={japanese_vocab_day}")
    if japanese_vocab_day < upstream_vocab_day:
        vocab_reasons.append(f"vocab-relative-stale:upstream={upstream_vocab_day}:japanese={japanese_vocab_day}")
    try:
        archive_vocab = load_json(JAPANESE, f"vocab/{today}.json")
        if str(archive_vocab.get("date") or "")[:10] != today:
            vocab_reasons.append(f"vocab-dated-archive-invalid:{today}.json")
    except (urllib.error.URLError, json.JSONDecodeError):
        vocab_reasons.append(f"vocab-dated-archive-missing:{today}.json")

    core_stale = bool(core_reasons)
    rolling_stale = bool(rolling_reasons)
    vocab_stale = bool(vocab_reasons)

    # Publication writers are deliberately serialized. A stage is only verified
    # from resulting data; completed workflow status alone never advances control.
    if core_stale:
        robot = choose_core_robot()
        reason = ";".join(core_reasons[:12])
        assigned = dispatch_robot(robot, reason=reason, serialize_writers=True)
        mark_job(state, "content-core", "assigned" if assigned else "waiting", reason=reason, robot=robot)
        print(f"NAS_CONTROLLER_RED stage=content-core robot={robot} reasons={reason}")
        return 1

    if rolling_stale:
        robot = choose_rolling_robot()
        reason = ";".join(rolling_reasons[:12])
        assigned = dispatch_robot(robot, reason=reason, serialize_writers=True)
        mark_job(state, "content-rolling", "assigned" if assigned else "waiting", reason=reason, robot=robot)
        print(f"NAS_CONTROLLER_RED stage=content-rolling robot={robot} reasons={reason}")
        return 1

    if vocab_stale:
        robot = choose_vocab_robot()
        reason = ";".join(vocab_reasons[:12])
        assigned = dispatch_robot(robot, reason=reason, serialize_writers=True)
        mark_job(state, "content-vocab", "assigned" if assigned else "waiting", reason=reason, robot=robot)
        print(f"NAS_CONTROLLER_RED stage=content-vocab robot={robot} reasons={reason}")
        return 1

    mark_job(state, "content-core", "verified", reason="source-current-and-translation-clean")
    mark_job(state, "content-rolling", "verified", reason="source-current-absolute-fresh-and-translation-clean")
    mark_job(state, "content-vocab", "verified", reason=f"today={today}-latest-and-dated-archive-current")

    f3_failures = verify_main_f3(japanese)
    if f3_failures:
        assigned = dispatch_robot("f3-voice", reason="main-f3-incomplete", serialize_writers=True)
        mark_job(
            state,
            "f3",
            "assigned" if assigned else "waiting",
            reason=";".join(f3_failures[:8]),
            robot="f3-voice",
        )
        print("NAS_CONTROLLER_RED stage=f3 " + " | ".join(f3_failures[:20]))
        return 1
    mark_job(state, "f3", "verified", reason="main-f3-assets-current")

    page_failures = verify_pages(japanese, japanese_vocab, today)
    if page_failures:
        assigned = dispatch_robot("pages-publisher", reason="pages-not-current")
        mark_job(
            state,
            "pages",
            "assigned" if assigned else "waiting",
            reason=";".join(page_failures[:8]),
            robot="pages-publisher",
        )
        print("NAS_CONTROLLER_RED stage=pages " + " | ".join(page_failures[:20]))
        return 1
    mark_job(state, "pages", "verified", reason="production-matches-main")

    fingerprint = publication_fingerprint(japanese, japanese_vocab)
    try:
        health = load_json(JAPANESE, "newsroom-health.json")
    except (urllib.error.URLError, json.JSONDecodeError):
        health = {}
    delivery = health.get("layers", {}).get("delivery", {})
    attested_at = parse_stamp({"checkedAt": delivery.get("attestedAt")})
    attestation_age = (
        (datetime.now(timezone.utc) - attested_at).total_seconds()
        if attested_at
        else None
    )
    if (
        health.get("state") == "GREEN"
        and delivery.get("attestedFingerprint") == fingerprint
        and attestation_age is not None
        and 0 <= attestation_age < 20 * 60
    ):
        mark_job(state, "delivery-attestation", "verified", reason="fresh-attestation", robot="delivery-auditor")
        print(
            "NAS_CONTROLLER_GREEN_ALREADY_ATTESTED "
            f"fingerprint={fingerprint} age_seconds={int(attestation_age)}"
        )
        return 0

    verified_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    assigned = dispatch_robot(
        "delivery-auditor",
        reason="all-stages-verified",
        inputs={"nas_verified_fingerprint": fingerprint, "nas_verified_at": verified_at},
    )
    mark_job(
        state,
        "delivery-attestation",
        "assigned" if assigned else "waiting",
        reason=fingerprint,
        robot="delivery-auditor",
    )
    if not assigned:
        print(f"NAS_CONTROLLER_VERIFY_PENDING fingerprint={fingerprint}")
        return 1
    print(f"NAS_CONTROLLER_GREEN_PENDING_ATTESTATION fingerprint={fingerprint} verified_at={verified_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
