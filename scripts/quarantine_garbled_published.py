#!/usr/bin/env python3
"""Fail closed on already-published rolling Japanese corruption.

If source-aware retranslation is temporarily unavailable, structurally garbled
copy must never remain visible. This emergency sanitizer replaces every visible
field of a contaminated story with a neutral Japanese repair marker, disables
its stale audio, and marks the story QUARANTINED. Front-end renderers skip that
story. The source-aware repair worker later removes the marker and restores the
real Japanese article after successful retranslation.
"""
from __future__ import annotations

import json
from pathlib import Path

import validate_content_integrity as core

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATIC = (DATA / "desk-latest.json", DATA / "stocks-latest.json")
VISIBLE_FIELDS = tuple(dict.fromkeys(core.STORY_TEXT_FIELDS + ("section",)))
PROSE_PLACEHOLDER = "翻訳品質を再検証中です。"
TITLE_PLACEHOLDER = "翻訳品質を再検証中のニュース"
TIME_PLACEHOLDER = "翻訳再検証中"
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
        and any(value.get(key) for key in ("dek", "summary", "body"))
    )


def field_bad(field, value):
    if not isinstance(value, str) or not value.strip():
        return False
    if core.ERROR_RE.search(value):
        return True
    if field in core.PROSE_FIELDS and core.prose_is_mixed(value):
        return True
    return bool(core.garbled_japanese_reason(value, strict=field in core.PROSE_FIELDS))


def story_bad(story):
    return any(field_bad(field, story.get(field)) for field in VISIBLE_FIELDS)


def quarantine_story(story, label):
    aid = str(story.get("id") or "unknown")
    print("QUARANTINE_GARBLED_STORY", label, aid)
    for field in VISIBLE_FIELDS:
        current = story.get(field)
        if not isinstance(current, str) or not current.strip():
            continue
        if field == "title":
            story[field] = TITLE_PLACEHOLDER
        elif field == "timeLabel":
            story[field] = TIME_PLACEHOLDER
        elif field == "section":
            # Keep a short valid section if it itself is not corrupt.
            if field_bad(field, current):
                story[field] = "ニュース"
        else:
            story[field] = PROSE_PLACEHOLDER
    story["qualityStatus"] = "QUARANTINED_GARBLED_TRANSLATION"
    story["furigana"] = {}
    story["audio"] = ""
    story["timing"] = ""


def sanitize_tree(value, label, path="$", in_story=False):
    changed = False
    if isinstance(value, dict):
        here_story = story_like(value)
        if here_story and story_bad(value):
            quarantine_story(value, label)
            return True
        for key, child in list(value.items()):
            if key == "furigana":
                continue
            child_path = f"{path}.{key}"
            if (
                not here_story
                and key in METADATA_KEYS
                and isinstance(child, str)
                and child.strip()
            ):
                reason = core.garbled_japanese_reason(child, strict=False)
                if reason:
                    print("QUARANTINE_GARBLED_METADATA", label, child_path, reason)
                    if key == "title":
                        value[key] = "ニュース"
                    elif key == "subtitle":
                        value[key] = "最新ニュースを掲載します。"
                    else:
                        value[key] = PROSE_PLACEHOLDER
                    changed = True
                    continue
            if isinstance(child, (dict, list)):
                changed = sanitize_tree(child, label, child_path, here_story) or changed
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                changed = sanitize_tree(child, label, f"{path}[{index}]", in_story) or changed
    return changed


def paths():
    out = [path for path in STATIC if path.is_file()]
    topic = DATA / "topic-more"
    if topic.is_dir():
        out.extend(sorted(topic.glob("*.json")))
    return out


def main():
    total = 0
    for path in paths():
        data = json.loads(path.read_text(encoding="utf-8"))
        label = str(path.relative_to(ROOT))
        if sanitize_tree(data, label):
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            total += 1
    print("GARBLED_PUBLICATION_QUARANTINE_OK", f"files_changed={total}")


if __name__ == "__main__":
    main()
