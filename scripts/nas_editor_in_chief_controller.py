#!/usr/bin/env python3
"""NAS-owned Editor-in-Chief control plane for the Japanese newsroom.

The NAS Editor-in-Chief is the sole scheduler. GitHub Actions are bounded
specialist robots. Every stage is verified against published data before the
next stage is allowed to run. If a primary robot finishes without fixing the
same source version, the controller switches to an alternate recovery path.
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
from typing import Dict, List, Optional, Set, Tuple


JAPANESE_REPOSITORY = os.getenv(
    "JAPANESE_GITHUB_REPOSITORY", "kanuli/daily-brief-newspaper-japanese"
)
UPSTREAM_REPOSITORY = os.getenv(
    "CANTONESE_GITHUB_REPOSITORY", "kanuli/daily-brief-newspaper"
)
REPOSITORY = JAPANESE_REPOSITORY
TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

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

HKT = timezone(timedelta(hours=8))
STOCK_MAX_AGE_SECONDS = int(os.getenv("STOCK_MAX_AGE_SECONDS", str(8 * 60 * 60)))
LAYERS = ("latest.json", "live.json", "desk-latest.json", "stocks-latest.json")

ROBOTS = {
    "core-translator": {
        "repo": JAPANESE_REPOSITORY,
        "workflow": "sync-japanese-news.yml",
    },
    "source-stock-primary": {
        "repo": UPSTREAM_REPOSITORY,
        "workflow": "stock-publication-maintenance.yml",
        "inputs": {"recovery_mode": "normal"},
    },
    "source-stock-deep": {
        "repo": UPSTREAM_REPOSITORY,
        "workflow": "stock-publication-maintenance.yml",
        "inputs": {"recovery_mode": "deep"},
    },
    "rolling-translator": {
        "repo": JAPANESE_REPOSITORY,
        "workflow": "repair-extra-translation-quality.yml",
    },
    "rolling-exhaustive-recovery": {
        "repo": JAPANESE_REPOSITORY,
        "workflow": "repair-all-published-quality.yml",
    },
    "source-vocab-generator": {
        "repo": UPSTREAM_REPOSITORY,
        "workflow": "daily-japanese-vocab.yml",
    },
    "vocab-translator": {
        "repo": JAPANESE_REPOSITORY,
        "workflow": "sync-daily-vocab.yml",
    },
    "vocab-exhaustive-recovery": {
        "repo": JAPANESE_REPOSITORY,
        "workflow": "recover-daily-vocab.yml",
    },
    "f3-voice": {
        "repo": JAPANESE_REPOSITORY,
        "workflow": "rebuild-f3-pacing.yml",
    },
    "pages-publisher": {
        "repo": JAPANESE_REPOSITORY,
        "workflow": "pages.yml",
    },
    "delivery-auditor": {
        "repo": JAPANESE_REPOSITORY,
        "workflow": "editor-in-chief-newsroom-robot.yml",
    },
    "discord-publisher": {
        "repo": JAPANESE_REPOSITORY,
        "workflow": "discord-after-pages.yml",
    },
}

MUTATING_ROBOTS = (
    "core-translator",
    "source-stock-primary",
    "source-stock-deep",
    "rolling-translator",
    "rolling-exhaustive-recovery",
    "source-vocab-generator",
    "vocab-translator",
    "vocab-exhaustive-recovery",
    "f3-voice",
    "pages-publisher",
    "delivery-auditor",
)


def request(url: str, *, method: str = "GET", payload: Optional[dict] = None) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
        "User-Agent": "nas-japanese-editor-in-chief-v3",
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
    raw = request(
        urllib.parse.urljoin(base, name) + f"{joiner}nas_verify={time.time_ns()}"
    )
    return json.loads(raw.decode("utf-8"))


def try_load_json(base: str, name: str) -> Optional[dict]:
    try:
        return load_json(base, name)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(
            f"EDITOR_READ_WARNING base={base} file={name} error={type(exc).__name__}:{exc}",
            file=sys.stderr,
        )
        return None


def parse_stamp(payload: Optional[dict]) -> Optional[datetime]:
    if not isinstance(payload, dict):
        return None
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
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def hkt_today() -> str:
    return datetime.now(HKT).date().isoformat()


def source_day(payload: Optional[dict]) -> str:
    return str((payload or {}).get("date") or "")[:10]


def publication_fingerprint(
    layers: Dict[str, dict], vocab: Optional[dict] = None
) -> str:
    return "|".join(
        (
            source_day(layers.get("latest.json")) or "missing",
            iso_millis(parse_stamp(layers.get("live.json"))),
            iso_millis(parse_stamp(layers.get("desk-latest.json"))),
            iso_millis(parse_stamp(layers.get("stocks-latest.json"))),
            source_day(vocab) or "missing",
        )
    )


def current(source: Optional[dict], local: Optional[dict], tolerance_seconds: int) -> bool:
    source_stamp = parse_stamp(source)
    local_stamp = parse_stamp(local)
    return bool(
        source_stamp
        and local_stamp
        and local_stamp.timestamp() + tolerance_seconds >= source_stamp.timestamp()
    )


def api_for(repo: str) -> str:
    return f"https://api.github.com/repos/{repo}"


def robot_spec(robot: str) -> dict:
    if robot not in ROBOTS:
        raise KeyError(f"unknown robot: {robot}")
    return ROBOTS[robot]


def workflow_runs(robot: str) -> list:
    spec = robot_spec(robot)
    workflow = urllib.parse.quote(str(spec["workflow"]), safe="")
    data = json.loads(
        request(
            f"{api_for(str(spec['repo']))}/actions/workflows/{workflow}/runs"
            "?branch=main&per_page=20"
        )
    )
    return list(data.get("workflow_runs") or [])


def active_run(robot: str) -> Optional[dict]:
    return next(
        (run for run in workflow_runs(robot) if run.get("status") != "completed"),
        None,
    )


def latest_completed_run(robot: str) -> Optional[dict]:
    return next(
        (run for run in workflow_runs(robot) if run.get("status") == "completed"),
        None,
    )


def parse_iso(value: object) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def any_mutating_robot_active(
    *, exclude_robot: Optional[str] = None
) -> Optional[Tuple[str, dict]]:
    seen = set()
    for robot in MUTATING_ROBOTS:
        if robot == exclude_robot:
            continue
        spec = robot_spec(robot)
        key = (str(spec["repo"]), str(spec["workflow"]))
        if key in seen:
            continue
        seen.add(key)
        run = active_run(robot)
        if run:
            return robot, run
    return None


def dispatch_robot(
    robot: str,
    *,
    reason: str,
    inputs: Optional[dict] = None,
    serialize_writers: bool = False,
) -> bool:
    spec = robot_spec(robot)
    workflow = str(spec["workflow"])
    repo = str(spec["repo"])

    own_active = active_run(robot)
    if own_active:
        print(
            "EDITOR_JOB_WAIT "
            f"robot={robot} repo={repo} workflow={workflow} "
            f"run={own_active.get('id')} reason={reason}"
        )
        return False

    if serialize_writers:
        blocker = any_mutating_robot_active(exclude_robot=robot)
        if blocker:
            blocker_robot, blocker_run = blocker
            blocker_spec = robot_spec(blocker_robot)
            print(
                "EDITOR_JOB_BLOCKED_BY_WRITER "
                f"robot={robot} blocker={blocker_robot} "
                f"blocker_repo={blocker_spec['repo']} "
                f"run={blocker_run.get('id')} reason={reason}"
            )
            return False

    merged_inputs = dict(spec.get("inputs") or {})
    if inputs:
        merged_inputs.update(inputs)

    payload = {"ref": "main"}
    if merged_inputs:
        payload["inputs"] = merged_inputs

    request(
        f"{api_for(repo)}/actions/workflows/{urllib.parse.quote(workflow, safe='')}/dispatches",
        method="POST",
        payload=payload,
    )
    print(
        "EDITOR_JOB_ASSIGNED "
        f"robot={robot} repo={repo} workflow={workflow} reason={reason}"
    )
    return True


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 3, "jobs": {}, "updatedAt": None}


def save_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state["version"] = 3
        state["updatedAt"] = (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        temp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
        temp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(STATE_PATH)
    except OSError as exc:
        print(
            f"EDITOR_STATE_WARNING path={STATE_PATH} error={exc}",
            file=sys.stderr,
        )


def mark_job(
    state: dict,
    job: str,
    status: str,
    *,
    reason: str,
    robot: Optional[str] = None,
    source_version: Optional[str] = None,
    attempts: Optional[int] = None,
) -> None:
    entry = {
        "status": status,
        "robot": robot,
        "reason": reason,
        "at": (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        ),
    }
    if source_version is not None:
        entry["sourceVersion"] = source_version
    if attempts is not None:
        entry["attempts"] = attempts
    state.setdefault("jobs", {})[job] = entry
    save_state(state)


def iter_stories(payload: object):
    if isinstance(payload, dict):
        if payload.get("id") and (
            payload.get("title") or payload.get("body") or payload.get("summary")
        ):
            yield payload
        for value in payload.values():
            yield from iter_stories(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from iter_stories(value)


def degraded_translation(payload: Optional[dict]) -> bool:
    if not isinstance(payload, dict):
        return True
    if bool(payload.get("translationDegraded")):
        return True
    if int(payload.get("translationDeferredCount") or 0) > 0:
        return True
    for story in iter_stories(payload):
        status = str(story.get("translationStatus") or "").strip().upper()
        if status in {
            "EDITORIAL_MINIMUM_FALLBACK",
            "TRANSLATION_FAILED",
            "TRANSLATION_DEGRADED",
        }:
            return True
    return False


def core_faults(upstream: Dict[str, dict], japanese: Dict[str, dict]) -> List[str]:
    failures = []
    source_latest_day = source_day(upstream["latest.json"])
    local_latest_day = source_day(japanese["latest.json"])
    if not source_latest_day:
        failures.append("daily-source-date-missing")
    elif not local_latest_day or local_latest_day < source_latest_day:
        failures.append(
            f"daily-date-lag:{local_latest_day or 'missing'}<{source_latest_day}"
        )

    source_live = parse_stamp(upstream["live.json"])
    local_live = parse_stamp(japanese["live.json"])
    if not source_live:
        failures.append("live-source-timestamp-missing")
    elif not local_live:
        failures.append("live-japanese-timestamp-missing")
    elif local_live.timestamp() + 60 < source_live.timestamp():
        lag = int((source_live - local_live).total_seconds() / 60)
        failures.append(f"live-lag-minutes:{lag}")

    if degraded_translation(japanese["latest.json"]):
        failures.append("daily-translation-degraded")
    if degraded_translation(japanese["live.json"]):
        failures.append("live-translation-degraded")
    return failures


def stock_source_faults(source_stocks: Optional[dict]) -> List[str]:
    stamp = parse_stamp(source_stocks)
    if not stamp:
        return ["stocks-upstream-timestamp-missing"]
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    if age < -300:
        return [f"stocks-upstream-clock-skew-seconds:{int(age)}"]
    if age > STOCK_MAX_AGE_SECONDS:
        return [
            "stocks-upstream-absolute-stale:"
            f"ageMinutes={int(age / 60)}:"
            f"maxHours={int(STOCK_MAX_AGE_SECONDS / 3600)}"
        ]
    return []


def rolling_faults(upstream: Dict[str, dict], japanese: Dict[str, dict]) -> List[str]:
    failures = []
    for label, name in (
        ("desk", "desk-latest.json"),
        ("stocks", "stocks-latest.json"),
    ):
        source_stamp = parse_stamp(upstream[name])
        local_stamp = parse_stamp(japanese[name])
        if not source_stamp:
            failures.append(f"{label}-source-timestamp-missing")
        elif not local_stamp:
            failures.append(f"{label}-japanese-timestamp-missing")
        elif local_stamp.timestamp() + 60 < source_stamp.timestamp():
            lag = int((source_stamp - local_stamp).total_seconds() / 60)
            failures.append(f"{label}-lag-minutes:{lag}")
        if degraded_translation(japanese[name]):
            failures.append(f"{label}-translation-degraded")
    return failures


def vocab_source_faults(source_vocab: Optional[dict], today: str) -> List[str]:
    if not isinstance(source_vocab, dict):
        return ["vocab-upstream-missing"]
    actual = source_day(source_vocab)
    if actual != today:
        return [f"vocab-upstream-date:{actual or 'missing'}!={today}"]
    return []


def vocab_faults(
    source_vocab: Optional[dict],
    local_vocab: Optional[dict],
    local_archive: Optional[dict],
    today: str,
) -> List[str]:
    failures = []
    if source_day(source_vocab) != today:
        failures.append(
            f"vocab-upstream-date:{source_day(source_vocab) or 'missing'}!={today}"
        )
        return failures
    if source_day(local_vocab) != today:
        failures.append(
            f"vocab-japanese-date:{source_day(local_vocab) or 'missing'}!={today}"
        )
    if local_archive is None:
        failures.append(f"vocab-dated-archive-missing:{today}.json")
    elif local_vocab != local_archive:
        failures.append("vocab-dated-archive-mismatch")
    return failures


def version_for_core(upstream: Dict[str, dict]) -> str:
    return "|".join(
        (
            source_day(upstream["latest.json"]) or "missing",
            iso_millis(parse_stamp(upstream["live.json"])),
        )
    )


def version_for_rolling(upstream: Dict[str, dict]) -> str:
    return "|".join(
        (
            iso_millis(parse_stamp(upstream["desk-latest.json"])),
            iso_millis(parse_stamp(upstream["stocks-latest.json"])),
        )
    )


def version_for_stock_source(source_stocks: Optional[dict]) -> str:
    return iso_millis(parse_stamp(source_stocks))


def previous_same_source(
    state: dict, stage: str, source_version: str
) -> Optional[dict]:
    job = (state.get("jobs") or {}).get(stage) or {}
    if job.get("sourceVersion") == source_version:
        return job
    return None


def choose_stock_robot(state: dict, source_version: str) -> str:
    if active_run("source-stock-primary"):
        prior = previous_same_source(state, "source-stocks", source_version) or {}
        return str(prior.get("robot") or "source-stock-primary")
    prior = previous_same_source(state, "source-stocks", source_version)
    if prior and prior.get("robot") in {"source-stock-primary", "source-stock-deep"}:
        return "source-stock-deep"
    return "source-stock-primary"


def choose_rolling_robot(state: dict, source_version: str) -> str:
    if active_run("rolling-exhaustive-recovery"):
        return "rolling-exhaustive-recovery"
    if active_run("rolling-translator"):
        return "rolling-translator"
    prior = previous_same_source(state, "content-rolling", source_version)
    if prior and prior.get("robot") in {
        "rolling-translator",
        "rolling-exhaustive-recovery",
    }:
        return "rolling-exhaustive-recovery"
    return "rolling-translator"


def choose_vocab_robot(state: dict, source_version: str) -> str:
    if active_run("vocab-exhaustive-recovery"):
        return "vocab-exhaustive-recovery"
    if active_run("vocab-translator"):
        return "vocab-translator"
    prior = previous_same_source(state, "vocab", source_version)
    if prior and prior.get("robot") in {
        "vocab-translator",
        "vocab-exhaustive-recovery",
    }:
        return "vocab-exhaustive-recovery"
    return "vocab-translator"


def discord_delivery_version(layers: Dict[str, dict]) -> str:
    live_stamp = parse_stamp(layers.get("live.json"))
    live_hour = (
        live_stamp.astimezone(HKT).strftime("%Y-%m-%dT%H")
        if live_stamp
        else "missing"
    )
    return f"{source_day(layers.get('latest.json')) or 'missing'}|{live_hour}"


def ensure_discord_delivery(state: dict, layers: Dict[str, dict]) -> bool:
    """Dispatch and verify one Discord publication per HKT Live publication hour."""
    source_version = discord_delivery_version(layers)
    job = (state.get("jobs") or {}).get("discord-delivery") or {}
    same_source = job.get("sourceVersion") == source_version

    if same_source and job.get("status") == "verified":
        print(
            "NAS_DISCORD_ALREADY_VERIFIED "
            f"sourceVersion={source_version}"
        )
        return True

    running = active_run("discord-publisher")
    if running:
        attempts = int(job.get("attempts") or 1) if same_source else 1
        mark_job(
            state,
            "discord-delivery",
            "waiting",
            reason=f"discord-workflow-active:run={running.get('id')}",
            robot="discord-publisher",
            source_version=source_version,
            attempts=attempts,
        )
        print(
            "NAS_CONTROLLER_RED stage=discord-delivery "
            f"status=waiting run={running.get('id')} sourceVersion={source_version}"
        )
        return False

    if same_source:
        latest = latest_completed_run("discord-publisher")
        assigned_at = parse_iso(job.get("at"))
        completed_at = parse_iso((latest or {}).get("updated_at") or (latest or {}).get("created_at"))
        if latest and assigned_at and completed_at and completed_at >= assigned_at:
            conclusion = str(latest.get("conclusion") or "")
            if conclusion in {"success", "neutral"}:
                mark_job(
                    state,
                    "discord-delivery",
                    "verified",
                    reason=f"discord-workflow-success:run={latest.get('id')}",
                    robot="discord-publisher",
                    source_version=source_version,
                    attempts=int(job.get("attempts") or 1),
                )
                print(
                    "NAS_DISCORD_DELIVERY_VERIFIED "
                    f"run={latest.get('id')} sourceVersion={source_version}"
                )
                return True

            attempts = int(job.get("attempts") or 1)
            if attempts >= 2:
                mark_job(
                    state,
                    "discord-delivery",
                    "waiting",
                    reason=f"discord-retry-budget-exhausted:{conclusion or 'unknown'}",
                    robot="discord-publisher",
                    source_version=source_version,
                    attempts=attempts,
                )
                print(
                    "NAS_CONTROLLER_RED stage=discord-delivery "
                    f"reason=retry-budget-exhausted conclusion={conclusion or 'unknown'} "
                    f"sourceVersion={source_version}"
                )
                return False

            assigned = dispatch_robot(
                "discord-publisher",
                reason=f"discord-retry-after-{conclusion or 'unknown'}",
            )
            mark_job(
                state,
                "discord-delivery",
                "assigned" if assigned else "waiting",
                reason=f"discord-retry-after-{conclusion or 'unknown'}",
                robot="discord-publisher",
                source_version=source_version,
                attempts=attempts + 1,
            )
            return False

    assigned = dispatch_robot(
        "discord-publisher",
        reason=f"verified-pages-hour:{source_version}",
    )
    mark_job(
        state,
        "discord-delivery",
        "assigned" if assigned else "waiting",
        reason="verified-pages-awaiting-discord-delivery",
        robot="discord-publisher",
        source_version=source_version,
        attempts=1,
    )
    print(
        "NAS_CONTROLLER_RED stage=discord-delivery "
        f"status={'assigned' if assigned else 'waiting'} sourceVersion={source_version}"
    )
    return False


def verify_main_f3(layers: Dict[str, dict]) -> List[str]:
    failures = []
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
                request(
                    urllib.parse.urljoin(JAPANESE_ROOT, audio)
                    + f"?nas_main_audio={time.time_ns()}"
                )
                timing_data = json.loads(
                    request(
                        urllib.parse.urljoin(JAPANESE_ROOT, timing)
                        + f"?nas_main_timing={time.time_ns()}"
                    ).decode("utf-8")
                )
                if timing_data.get("deliveryProfile") != "jp-tv-news-semantic-v4":
                    failures.append(f"f3:{story.get('id')}:wrong-profile")
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                failures.append(f"f3:{story.get('id')}:{type(exc).__name__}")
    return failures


def verify_pages(
    layers: Dict[str, dict], vocab: Optional[dict], today: str
) -> List[str]:
    failures = []
    for name, expected in layers.items():
        try:
            published = load_json(PAGES + "data/", name)
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            failures.append(f"pages:{name}:{type(exc).__name__}")
            continue
        if name == "latest.json":
            if source_day(published) < source_day(expected):
                failures.append(f"pages:{name}:stale")
        elif not current(expected, published, 0):
            failures.append(f"pages:{name}:stale")
        if degraded_translation(published):
            failures.append(f"pages:{name}:degraded-translation")

    if vocab is not None:
        published_vocab = try_load_json(PAGES + "data/vocab/", "latest.json")
        published_archive = try_load_json(PAGES + "data/vocab/", f"{today}.json")
        if source_day(published_vocab) != source_day(vocab):
            failures.append("pages:vocab-latest:stale")
        elif published_vocab != vocab:
            failures.append("pages:vocab-latest:content-mismatch")
        if published_archive is None:
            failures.append(f"pages:vocab-archive:{today}:missing")
        elif published_archive != vocab:
            failures.append(f"pages:vocab-archive:{today}:content-mismatch")

    seen = set()  # type: Set[Tuple[str, str]]
    for payload in layers.values():
        for story in iter_stories(payload):
            audio = str(story.get("audio") or "")
            timing = str(story.get("timing") or "")
            if not audio or not timing or (audio, timing) in seen:
                continue
            seen.add((audio, timing))
            try:
                request(
                    urllib.parse.urljoin(PAGES, audio)
                    + f"?nas_page_audio={time.time_ns()}"
                )
                timing_data = json.loads(
                    request(
                        urllib.parse.urljoin(PAGES, timing)
                        + f"?nas_page_timing={time.time_ns()}"
                    ).decode("utf-8")
                )
                if timing_data.get("deliveryProfile") != "jp-tv-news-semantic-v4":
                    failures.append(f"pages-f3:{story.get('id')}:wrong-profile")
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                failures.append(f"pages-f3:{story.get('id')}:{type(exc).__name__}")
    return failures


def main() -> int:
    if not TOKEN:
        print(
            "NAS_CONTROLLER_RED GITHUB_TOKEN is required for workflow dispatch",
            file=sys.stderr,
        )
        return 2

    state = load_state()
    today = hkt_today()

    upstream = {name: load_json(UPSTREAM, name) for name in LAYERS}
    japanese = {name: load_json(JAPANESE, name) for name in LAYERS}
    source_vocab = try_load_json(UPSTREAM + "vocab/", "latest.json")
    local_vocab = try_load_json(JAPANESE + "vocab/", "latest.json")
    local_vocab_archive = try_load_json(JAPANESE + "vocab/", f"{today}.json")

    core_reasons = core_faults(upstream, japanese)
    stock_source_reasons = stock_source_faults(upstream["stocks-latest.json"])
    rolling_reasons = rolling_faults(upstream, japanese)
    source_vocab_reasons = vocab_source_faults(source_vocab, today)
    local_vocab_reasons = vocab_faults(
        source_vocab, local_vocab, local_vocab_archive, today
    )

    if core_reasons:
        source_version = version_for_core(upstream)
        reason = ";".join(core_reasons)
        robot = "core-translator"
        assigned = dispatch_robot(robot, reason=reason, serialize_writers=True)
        mark_job(
            state,
            "content-core",
            "assigned" if assigned else "waiting",
            reason=reason,
            robot=robot,
            source_version=source_version,
        )
        print(
            "NAS_CONTROLLER_RED stage=content-core "
            f"reasons={reason} sourceVersion={source_version}"
        )
        return 1
    mark_job(
        state,
        "content-core",
        "verified",
        reason="source-current-nondegraded",
        source_version=version_for_core(upstream),
    )

    if stock_source_reasons:
        source_version = version_for_stock_source(upstream["stocks-latest.json"])
        reason = ";".join(stock_source_reasons)
        robot = choose_stock_robot(state, source_version)
        assigned = dispatch_robot(robot, reason=reason, serialize_writers=True)
        mark_job(
            state,
            "source-stocks",
            "assigned" if assigned else "waiting",
            reason=reason,
            robot=robot,
            source_version=source_version,
        )
        print(
            "NAS_CONTROLLER_RED stage=source-stocks "
            f"robot={robot} reasons={reason} sourceVersion={source_version}"
        )
        return 1
    mark_job(
        state,
        "source-stocks",
        "verified",
        reason="upstream-stock-absolute-fresh",
        source_version=version_for_stock_source(upstream["stocks-latest.json"]),
    )

    if rolling_reasons:
        source_version = version_for_rolling(upstream)
        reason = ";".join(rolling_reasons)
        robot = choose_rolling_robot(state, source_version)
        assigned = dispatch_robot(robot, reason=reason, serialize_writers=True)
        mark_job(
            state,
            "content-rolling",
            "assigned" if assigned else "waiting",
            reason=reason,
            robot=robot,
            source_version=source_version,
        )
        print(
            "NAS_CONTROLLER_RED stage=content-rolling "
            f"robot={robot} reasons={reason} sourceVersion={source_version}"
        )
        return 1
    mark_job(
        state,
        "content-rolling",
        "verified",
        reason="source-current-nondegraded",
        source_version=version_for_rolling(upstream),
    )

    if source_vocab_reasons:
        source_version = source_day(source_vocab) or "missing"
        reason = ";".join(source_vocab_reasons)
        robot = "source-vocab-generator"
        assigned = dispatch_robot(robot, reason=reason, serialize_writers=True)
        mark_job(
            state,
            "source-vocab",
            "assigned" if assigned else "waiting",
            reason=reason,
            robot=robot,
            source_version=source_version,
        )
        print(
            "NAS_CONTROLLER_RED stage=source-vocab "
            f"robot={robot} reasons={reason} sourceVersion={source_version}"
        )
        return 1
    mark_job(
        state,
        "source-vocab",
        "verified",
        reason=f"upstream-vocab-current:{today}",
        source_version=source_day(source_vocab),
    )

    if local_vocab_reasons:
        source_version = source_day(source_vocab) or today
        reason = ";".join(local_vocab_reasons)
        robot = choose_vocab_robot(state, source_version)
        assigned = dispatch_robot(robot, reason=reason, serialize_writers=True)
        mark_job(
            state,
            "vocab",
            "assigned" if assigned else "waiting",
            reason=reason,
            robot=robot,
            source_version=source_version,
        )
        print(
            "NAS_CONTROLLER_RED stage=vocab "
            f"robot={robot} reasons={reason} sourceVersion={source_version}"
        )
        return 1
    mark_job(
        state,
        "vocab",
        "verified",
        reason=f"latest-and-dated-archive-current:{today}",
        source_version=source_day(source_vocab),
    )

    f3_failures = verify_main_f3(japanese)
    if f3_failures:
        reason = ";".join(f3_failures[:8])
        assigned = dispatch_robot(
            "f3-voice", reason=reason, serialize_writers=True
        )
        mark_job(
            state,
            "f3",
            "assigned" if assigned else "waiting",
            reason=reason,
            robot="f3-voice",
        )
        print("NAS_CONTROLLER_RED stage=f3 " + " | ".join(f3_failures[:20]))
        return 1
    mark_job(state, "f3", "verified", reason="main-f3-assets-current")

    page_failures = verify_pages(japanese, local_vocab, today)
    if page_failures:
        reason = ";".join(page_failures[:8])
        assigned = dispatch_robot(
            "pages-publisher", reason=reason, serialize_writers=True
        )
        mark_job(
            state,
            "pages",
            "assigned" if assigned else "waiting",
            reason=reason,
            robot="pages-publisher",
        )
        print("NAS_CONTROLLER_RED stage=pages " + " | ".join(page_failures[:20]))
        return 1
    mark_job(
        state,
        "pages",
        "verified",
        reason="production-matches-main-including-vocab",
    )

    fingerprint = publication_fingerprint(japanese, local_vocab)
    health = try_load_json(JAPANESE, "newsroom-health.json") or {}
    delivery = (health.get("layers") or {}).get("delivery") or {}
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
        mark_job(
            state,
            "delivery-attestation",
            "verified",
            reason="fresh-attestation",
            robot="delivery-auditor",
            source_version=fingerprint,
        )
        if not ensure_discord_delivery(state, japanese):
            return 1
        print(
            "NAS_CONTROLLER_GREEN "
            f"fingerprint={fingerprint} age_seconds={int(attestation_age)} "
            "discord=verified"
        )
        return 0

    verified_at = (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    assigned = dispatch_robot(
        "delivery-auditor",
        reason="all-stages-verified-awaiting-independent-attestation",
        inputs={
            "nas_verified_fingerprint": fingerprint,
            "nas_verified_at": verified_at,
        },
        serialize_writers=True,
    )
    mark_job(
        state,
        "delivery-attestation",
        "assigned" if assigned else "waiting",
        reason=f"fingerprint={fingerprint};priorHealth={health.get('state') or 'missing'}",
        robot="delivery-auditor",
        source_version=fingerprint,
    )
    print(
        "NAS_CONTROLLER_VERIFY_PENDING "
        f"fingerprint={fingerprint} auditorAssigned={assigned}"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
