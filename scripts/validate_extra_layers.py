#!/usr/bin/env python3
"""Validate translated rolling/topic layers before publication and F3 synthesis."""
import json
import sys
from pathlib import Path

import validate_content_integrity as core

ROOT = Path(__file__).resolve().parents[1]
STATIC = (ROOT / "data/desk-latest.json", ROOT / "data/stocks-latest.json")


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


def paths():
    out = [p for p in STATIC if p.is_file()]
    folder = ROOT / "data/topic-more"
    if folder.is_dir():
        out.extend(sorted(folder.glob("*.json")))
    return out


def validate(path):
    issues = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"{path.relative_to(ROOT)}: {exc}"]
    label = str(path.relative_to(ROOT))
    if not isinstance(data, dict) or data.get("language") != "ja":
        issues.append(f"{label}: language != ja")
        return issues
    for key, value in core.iter_strings(data):
        if core.ERROR_RE.search(value):
            issues.append(f"{label}:{key}: translator/server error payload detected")
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


def main():
    found = paths()
    if not found:
        print("EXTRA_LAYER_INTEGRITY_FAIL: no extra translated data files")
        return 1
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
    print("EXTRA_LAYER_INTEGRITY_OK", ", ".join(str(p.relative_to(ROOT)) for p in found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
