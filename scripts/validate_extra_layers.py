#!/usr/bin/env python3
"""Validate only rolling/topic layers that are currently eligible to render.

A stale rolling payload is quarantined by the topic renderer and therefore must
not block deployment merely because old copy still exists in the repository.
Fresh/renderable rolling content remains fail-closed.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import editor_in_chief_review as editor_in_chief
import validate_content_integrity as core

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATIC = (DATA / "desk-latest.json", DATA / "stocks-latest.json")
ROLLING_LAYER_MAX_AGE_DAYS = 1
METADATA_KEYS = {
    "title", "subtitle", "tagline", "section", "label", "statusLabel",
    "impactLabel", "description", "note", "lastUpdatedLabel",
}


def story_like(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and bool(value.get("id"))
        and isinstance(value.get("title"), str)
        and bool(value.get("title"))
        and any(value.get(k) for k in ("dek", "summary", "body"))
    )


def iter_stories(value):
    if story_like(value):
        yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from iter_stories(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_stories(child)


def iter_metadata(value, path="$"):
    """Yield visible non-furigana metadata strings throughout a rolling file."""
    if isinstance(value, dict):
        is_story = story_like(value)
        for key, child in value.items():
            if key == "furigana":
                continue
            child_path = f"{path}.{key}"
            if key in METADATA_KEYS and isinstance(child, str) and child.strip():
                if not (is_story and key in core.STORY_TEXT_FIELDS):
                    yield child_path, child
            if isinstance(child, (dict, list)):
                yield from iter_metadata(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_metadata(child, f"{path}[{index}]")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_day(value) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def current_publication_day() -> date | None:
    """Use the newest reader-facing edition boundary, not Daily alone.

    Live can roll into the next HKT calendar day before the next Daily edition is
    cut.  A same-day rolling desk must remain publishable in that interval.
    """
    days: list[date] = []
    for name in ("latest.json", "live.json"):
        path = DATA / name
        if not path.is_file():
            continue
        try:
            parsed = parse_day(load_json(path).get("date"))
        except Exception:
            parsed = None
        if parsed:
            days.append(parsed)
    return max(days) if days else None


def current_daily_day() -> date | None:
    """Daily date still owns the topic-more filename."""
    path = DATA / "latest.json"
    if not path.is_file():
        return None
    try:
        return parse_day(load_json(path).get("date"))
    except Exception:
        return None


def payload_day(path: Path) -> date | None:
    try:
        data = load_json(path)
    except Exception:
        return None
    return parse_day(data.get("date") or data.get("generatedAt"))


def static_layer_publishable(path: Path, current: date | None) -> bool:
    if not path.is_file():
        return False
    if current is None:
        return False
    candidate = payload_day(path)
    if candidate is None:
        return False
    age = (current - candidate).days
    return 0 <= age <= ROLLING_LAYER_MAX_AGE_DAYS


def paths():
    """Return only layers the current frontend is allowed to render."""
    current = current_publication_day()
    daily = current_daily_day()
    out: list[Path] = []

    for path in STATIC:
        if static_layer_publishable(path, current):
            out.append(path)
        elif path.is_file():
            candidate = payload_day(path)
            age = (current - candidate).days if current and candidate else "unknown"
            print(
                "EXTRA_LAYER_STALE_QUARANTINED",
                str(path.relative_to(ROOT)),
                f"age_days={age}",
                f"publication_day={current}",
                "renderable=false",
            )

    # Topic pages request topic-more/<Daily date>.json. Historical topic-more
    # files remain archive material even when Live has crossed midnight.
    if daily:
        current_name = daily.isoformat()
        topic = DATA / "topic-more" / f"{current_name}.json"
        if topic.is_file():
            out.append(topic)

    return out


def validate(path):
    issues = []
    try:
        data = load_json(path)
    except Exception as exc:
        return [f"{path.relative_to(ROOT)}: {exc}"]
    label = str(path.relative_to(ROOT))
    if not isinstance(data, dict) or data.get("language") != "ja":
        issues.append(f"{label}: language != ja")
        return issues

    for key, value in core.iter_strings(data):
        if core.ERROR_RE.search(value):
            issues.append(f"{label}:{key}: translator/server error payload detected")

    for key, value in iter_metadata(data):
        reason = core.garbled_japanese_reason(value, strict=False)
        if reason:
            issues.append(f"{label}:{key}: garbled visible metadata: {reason}")

    count = 0
    for story in iter_stories(data):
        count += 1
        aid = story.get("id") or "unknown"
        issues.extend(core.collect_story_issues(label, story))
        furigana = story.get("furigana")
        if not isinstance(furigana, dict):
            issues.append(f"{label}:{aid}: missing furigana metadata")
        if not str(story.get("audio") or "").startswith("audio/rolling/"):
            issues.append(f"{label}:{aid}: missing rolling F3 audio path")
        if not str(story.get("timing") or "").startswith("audio/timing/rolling/"):
            issues.append(f"{label}:{aid}: missing rolling F3 timing path")
    if count == 0 and path.name in {"desk-latest.json", "stocks-latest.json"}:
        issues.append(f"{label}: no translated rolling stories found")
    return issues


def review_publishable(found: list[Path]) -> int:
    """Run Editor-in-Chief only on layers that can actually reach a reader."""
    issues: list[str] = []
    warnings: list[str] = []
    reviewed = 0

    # The display-level freshness guard is mandatory even when every rolling
    # payload is currently stale, because it is what makes quarantine truthful.
    editor_in_chief.check_topic_freshness_delivery(issues, warnings)

    for path in found:
        name = str(path.relative_to(DATA))
        try:
            data = load_json(path)
        except Exception as exc:
            issues.append(f"{name}: unreadable JSON: {type(exc).__name__}: {exc}")
            continue
        source_map = editor_in_chief.source_map_for(name)
        for story in editor_in_chief.iter_story_dicts(data):
            reviewed += 1
            sid = str(story.get("id") or "")
            editor_in_chief.check_story(name, story, source_map.get(sid), issues, warnings)

    for warning in warnings[:100]:
        print("EDITOR_IN_CHIEF_WARNING -", warning)
    if len(warnings) > 100:
        print(f"EDITOR_IN_CHIEF_WARNING - ... and {len(warnings) - 100} more")

    if issues:
        print(
            "EDITOR_IN_CHIEF_REJECT",
            "scope=publishable-rolling",
            f"reviewed_stories={reviewed}",
            f"issues={len(issues)}",
            f"warnings={len(warnings)}",
        )
        for issue in issues[:100]:
            print(" -", issue)
        return 1

    print(
        "EDITOR_IN_CHIEF_APPROVED",
        "scope=publishable-rolling",
        f"reviewed_stories={reviewed}",
        f"warnings={len(warnings)}",
        "stale_layers_quarantined=true",
    )
    return 0


def main():
    found = paths()
    issues = []
    for path in found:
        issues.extend(validate(path))
    if issues:
        print("EXTRA_LAYER_INTEGRITY_FAIL")
        for issue in issues[:120]:
            print(" -", issue)
        if len(issues) > 120:
            print(f" - ... and {len(issues) - 120} more")
        return 1

    if review_publishable(found) != 0:
        print("EXTRA_LAYER_INTEGRITY_FAIL - Editor-in-Chief rejected publishable rolling content")
        return 1

    if found:
        labels = ", ".join(str(p.relative_to(ROOT)) for p in found)
    else:
        labels = "no current publishable rolling layers (stale layers quarantined)"
    print("EXTRA_LAYER_INTEGRITY_OK", labels, "editor_in_chief=approved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
