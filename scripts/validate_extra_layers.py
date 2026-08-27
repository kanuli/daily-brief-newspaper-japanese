#!/usr/bin/env python3
"""Validate translated rolling/topic layers before publication and F3 synthesis."""
import json
import sys
from pathlib import Path

import editor_in_chief_review as editor_in_chief
import validate_content_integrity as core

ROOT = Path(__file__).resolve().parents[1]
STATIC = (ROOT / "data/desk-latest.json", ROOT / "data/stocks-latest.json")
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
                # Story text itself is checked by collect_story_issues below;
                # keep this pass focused on page/section/ticker metadata.
                if not (is_story and key in core.STORY_TEXT_FIELDS):
                    yield child_path, child
            if isinstance(child, (dict, list)):
                yield from iter_metadata(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_metadata(child, f"{path}[{index}]")


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

    # Page/section/ticker metadata used to escape the story-only checker. The
    # same corruption signatures must apply to these visible strings too.
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

    # Auto-maintenance already treats this validator as the rolling health
    # authority. Include the rolling Editor-in-Chief verdict so only the
    # rolling repair worker is dispatched for editorial defects in that domain.
    editor_code = editor_in_chief.review("rolling")
    if editor_code != 0:
        print("EXTRA_LAYER_INTEGRITY_FAIL - Editor-in-Chief rejected rolling publication")
        return 1

    print(
        "EXTRA_LAYER_INTEGRITY_OK",
        ", ".join(str(p.relative_to(ROOT)) for p in found),
        "editor_in_chief=approved",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
