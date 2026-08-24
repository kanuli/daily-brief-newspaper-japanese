#!/usr/bin/env python3
"""Translate Cantonese rolling/topic data into Japanese without editorial drift.

The Cantonese repository is the only news-collection source of truth. This
script preserves the complete source structure and story set, translates only
user-facing text, adds furigana metadata for news content, and attaches paths
for server-side Supertonic 3 F3 audio.
"""
import hashlib
import json
import re
from pathlib import Path

import requests

import safe_sync as safe
import sync_and_translate as base

OUT = Path("data")
SOURCE_BASE = base.SOURCE_BASE
SCHEMA = "ja-cantonese-extra-v2-full-parity"
STATIC_FILES = ("desk-latest.json", "stocks-latest.json")


def fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def story_like(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and bool(value.get("id"))
        and isinstance(value.get("title"), str)
        and bool(value.get("title"))
        and any(value.get(k) for k in ("dek", "summary", "body"))
    )


def decorate_story_tree(value, group="rolling"):
    if isinstance(value, list):
        for child in value:
            decorate_story_tree(child, group)
        return value
    if not isinstance(value, dict):
        return value

    if story_like(value):
        furigana = {}
        for field in base.RUBY_FIELDS:
            text = value.get(field)
            if isinstance(text, str) and text.strip():
                furigana[field] = base.ruby_html(text)
        furigana["bodyParagraphs"] = [base.ruby_html(p) for p in base.body_paragraphs(value)]
        value["furigana"] = furigana
        aid = value["id"]
        value["audio"] = f"audio/{group}/{aid}.mp3"
        value["timing"] = f"audio/timing/{group}/{aid}.json"

    for key, child in list(value.items()):
        if key == "furigana":
            continue
        decorate_story_tree(child, group)
    return value


def fetch_source(name, optional=False):
    response = requests.get(
        f"{SOURCE_BASE}/{name}",
        timeout=40,
        headers={"User-Agent": "daily-brief-newspaper-japanese-cantonese-parity"},
    )
    if optional and response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def existing_current(path, source_hash):
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        isinstance(data, dict)
        and data.get("language") == "ja"
        and data.get("translationSchemaVersion") == SCHEMA
        and data.get("sourceFingerprint") == source_hash
    )


def translate_file(name, source):
    # IMPORTANT: never compact, cap, rank, drop, or independently select stories
    # here. The Cantonese source structure is preserved exactly before Japanese
    # text decoration so both editions share the same collected news resources.
    source_hash = fingerprint(source)
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if existing_current(path, source_hash):
        print("EXTRA_FAST_PATH", name)
        return False

    translated = safe.safe_convert(source)
    decorate_story_tree(translated, "rolling")
    if isinstance(translated, dict):
        translated["language"] = "ja"
        translated["translationSource"] = "kanuli/daily-brief-newspaper"
        translated["sourceFile"] = name
        translated["sourceFingerprint"] = source_hash
        translated["translationSchemaVersion"] = SCHEMA
        translated["sourceParityMode"] = "full-source-preserved"
    path.write_text(json.dumps(translated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXTRA_TRANSLATED_FULL_PARITY", name)
    return True


def current_date():
    path = OUT / "latest.json"
    if not path.is_file():
        raise RuntimeError("data/latest.json must exist before extra-layer sync")
    data = json.loads(path.read_text(encoding="utf-8"))
    value = str(data.get("date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise RuntimeError(f"invalid latest date: {value!r}")
    return value


def prune_old_topic_more(today):
    folder = OUT / "topic-more"
    if not folder.exists():
        return
    for path in folder.glob("*.json"):
        if path.name != f"{today}.json":
            path.unlink()


def main():
    base.translate_part = lambda part: safe.safe_translate_part(part, strict=False)
    base.translate_text = lambda text: safe.safe_translate_text(text, strict=False)
    base.convert = safe.safe_convert
    base.TRANSLATE_KEYS.update({"impactLabel"})
    safe.prune_cache()

    OUT.mkdir(exist_ok=True)
    date = current_date()
    names = [*STATIC_FILES, f"topic-more/{date}.json"]
    changed = []
    for name in names:
        source = fetch_source(name, optional=name.startswith("topic-more/"))
        if source is None:
            continue
        if translate_file(name, source):
            changed.append(name)

    prune_old_topic_more(date)
    base.CACHE_PATH.write_text(json.dumps(base.CACHE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXTRA_LAYER_FULL_PARITY_OK", ", ".join(changed) if changed else "no effective changes")


if __name__ == "__main__":
    main()
