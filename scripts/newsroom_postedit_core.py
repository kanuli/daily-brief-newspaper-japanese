#!/usr/bin/env python3
"""Dependency-light deterministic post-edit for current Daily/Live Japanese.

Used after remote emergency sync where the local OPUS-MT repair stack is not
installed. It never invents facts or performs network translation: it applies
only meaning-preserving terminology normalizations, fixes known section labels,
and re-renders furigana through the active safe lexical engine.
"""
from __future__ import annotations

import json
from pathlib import Path

import cantonese_snapshot as snapshot
import furigana_safe_runtime
import newsroom_quality
import sync_and_translate as base

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FILES = (("latest.json", "articles"), ("live.json", "items"))
FIELDS = ("section", "title", "dek", "summary", "body", "context", "why", "watchNext")


def index(items):
    return {str(item.get("id")): item for item in items or [] if item.get("id")}


def rerender(data: dict, key: str) -> dict:
    if key == "articles":
        data = base.add_furigana(base.attach_daily_audio(data), key)
    else:
        data = base.add_furigana(base.attach_live_audio(data), key)
    data["furiganaEngineVersion"] = furigana_safe_runtime.engine_name()
    data["newsroomQualityVersion"] = 1
    return data


def repair(name: str, key: str) -> int:
    path = DATA / name
    source = snapshot.load_json(name)
    target = json.loads(path.read_text(encoding="utf-8"))
    src = index(source.get(key, []))
    changed = 0

    for item in target.get(key, []) or []:
        source_item = src.get(str(item.get("id")))
        if not source_item:
            continue
        item_changed = False
        for field in FIELDS:
            source_text = source_item.get(field)
            current = item.get(field)
            if not isinstance(source_text, str) or not isinstance(current, str):
                continue
            polished = newsroom_quality.deterministic_postedit(source_text, current, field)
            if polished != current:
                item[field] = polished
                changed += 1
                item_changed = True
        source_label = source_item.get("sectionLabel")
        if isinstance(source_label, str):
            mapped = base.ARCHIVE_TOPIC_NAMES.get(source_label)
            if mapped and item.get("sectionLabel") != mapped:
                item["sectionLabel"] = mapped
                changed += 1
                item_changed = True
        if item_changed:
            item.pop("furigana", None)

    # Always rerender once so a new lexical engine is migrated even when prose
    # itself required no deterministic edits.
    target = rerender(target, key)
    path.write_text(json.dumps(target, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("NEWSROOM_POSTEDIT_FILE", name, f"fields={changed}", f"engine={furigana_safe_runtime.engine_name()}")
    return changed


def main():
    furigana_safe_runtime.install()
    total = 0
    for name, key in FILES:
        total += repair(name, key)
    print("NEWSROOM_POSTEDIT_OK", f"fields={total}", f"snapshot={snapshot.snapshot_commit()}")


if __name__ == "__main__":
    main()
