#!/usr/bin/env python3
"""Fail closed on already-published rolling Japanese corruption.

Structurally garbled or previously quarantined stories must not remain visible.
This sanitizer removes contaminated story records from published rolling JSON
until the source-aware repair worker can restore a clean Japanese replacement.
It never substitutes a visible "translation under review" placeholder.
"""
from __future__ import annotations

import json
from pathlib import Path

import validate_content_integrity as core

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATIC = (DATA / "desk-latest.json", DATA / "stocks-latest.json")
VISIBLE_FIELDS = tuple(dict.fromkeys(core.STORY_TEXT_FIELDS + ("section",)))
OLD_TITLE_PLACEHOLDER = "翻訳品質を再検証中のニュース"
OLD_PROSE_PLACEHOLDER = "翻訳品質を再検証中です。"
OLD_TIME_PLACEHOLDER = "翻訳再検証中"
QUARANTINE_STATUS = "QUARANTINED_GARBLED_TRANSLATION"
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
    if value.strip() in {OLD_TITLE_PLACEHOLDER, OLD_PROSE_PLACEHOLDER, OLD_TIME_PLACEHOLDER}:
        return True
    if core.ERROR_RE.search(value):
        return True
    if field in core.PROSE_FIELDS and core.prose_is_mixed(value):
        return True
    return bool(core.garbled_japanese_reason(value, strict=field in core.PROSE_FIELDS))


def previously_quarantined(story):
    return (
        str(story.get("qualityStatus") or "") == QUARANTINE_STATUS
        or str(story.get("title") or "").strip() == OLD_TITLE_PLACEHOLDER
    )


def story_bad(story):
    if previously_quarantined(story):
        return True
    return any(field_bad(field, story.get(field)) for field in VISIBLE_FIELDS)


def sanitize_tree(value, label, path="$", in_story=False):
    changed = False
    if isinstance(value, dict):
        here_story = story_like(value)
        for key, child in list(value.items()):
            if key == "furigana":
                continue
            child_path = f"{path}.{key}"

            if isinstance(child, dict) and story_like(child) and story_bad(child):
                print("DROP_GARBLED_STORY", label, str(child.get("id") or "unknown"), child_path)
                del value[key]
                changed = True
                continue

            if (
                not here_story
                and key in METADATA_KEYS
                and isinstance(child, str)
                and child.strip()
            ):
                reason = core.garbled_japanese_reason(child, strict=False)
                is_old_placeholder = child.strip() in {
                    OLD_TITLE_PLACEHOLDER,
                    OLD_PROSE_PLACEHOLDER,
                    OLD_TIME_PLACEHOLDER,
                }
                if reason or is_old_placeholder:
                    print("CLEAR_GARBLED_METADATA", label, child_path, reason or "old quarantine placeholder")
                    if key == "title":
                        value[key] = "ニュース"
                    elif key == "subtitle":
                        value[key] = "最新ニュースを掲載します。"
                    else:
                        value[key] = ""
                    changed = True
                    continue

            if isinstance(child, (dict, list)):
                changed = sanitize_tree(child, label, child_path, here_story) or changed

    elif isinstance(value, list):
        kept = []
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            if isinstance(child, dict) and story_like(child) and story_bad(child):
                print("DROP_GARBLED_STORY", label, str(child.get("id") or "unknown"), child_path)
                changed = True
                continue
            if isinstance(child, (dict, list)):
                changed = sanitize_tree(child, label, child_path, in_story) or changed
            kept.append(child)
        if len(kept) != len(value):
            value[:] = kept

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
    print("GARBLED_PUBLICATION_DROP_OK", f"files_changed={total}")


if __name__ == "__main__":
    main()
