#!/usr/bin/env python3
"""Repair garbled Japanese in the already-built Daily/Live core publication.

The normal parity sync remains responsible for adding/removing stories and for
advancing the publication window.  This worker is a quality backstop: after
that structural sync it compares the Japanese stories with the same frozen
Cantonese snapshot, retranslates only fields rejected by the production quality
gate, and rebuilds furigana/audio metadata before publication.

Known-bad text is repaired with the validated free remote fallback chain first.
The local OPUS-MT path is used only as a final fallback so maintenance does not
reproduce the same poisoned local output indefinitely.
"""
from __future__ import annotations

import json
from pathlib import Path

import cantonese_snapshot as snapshot
import furigana_safe_runtime
import local_metadata_overrides as metadata_overrides
import local_translation_runtime as runtime
import safe_sync as safe
import sync_and_translate as base
import sync_cantonese_layers as extra
import validate_content_integrity as integrity

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CORE_FILES = ("latest.json", "live.json")
CORE_FIELDS = ("section",) + integrity.STORY_TEXT_FIELDS


def index_stories(value, out=None):
    if out is None:
        out = {}
    if extra.story_like(value):
        out[str(value.get("id"))] = value
    if isinstance(value, dict):
        for child in value.values():
            index_stories(child, out)
    elif isinstance(value, list):
        for child in value:
            index_stories(child, out)
    return out


def bad_translation(source_text: str, japanese_text: str, strict: bool) -> bool:
    if not isinstance(japanese_text, str) or not japanese_text.strip():
        return True
    if integrity.ERROR_RE.search(japanese_text):
        return True
    if strict and integrity.prose_is_mixed(japanese_text):
        return True
    if integrity.garbled_japanese_reason(japanese_text, strict=strict):
        return True
    return not safe.target_quality_ok(source_text, japanese_text, strict=strict)


def repair_value(source_text: str, strict: bool) -> str:
    remote_error = None
    try:
        value = runtime._remote_quality_fallback(source_text, strict=strict)
        if not bad_translation(source_text, value, strict):
            return value
        remote_error = RuntimeError("remote fallback returned rejected text")
    except Exception as exc:
        remote_error = exc
        print(
            "CORE_TARGET_REMOTE_REPAIR_DEFER",
            f"source={source_text[:80]!r}",
            f"error={type(exc).__name__}:{exc}",
        )

    value = runtime.localize_or_translate(source_text, strict=strict)
    if bad_translation(source_text, value, strict):
        raise RuntimeError(
            "Core targeted repair failed after remote-first and local fallback: "
            f"remote={remote_error}"
        )
    return value


def repair_file(name: str, source) -> int:
    path = DATA / name
    if not path.is_file():
        print("CORE_TARGET_REPAIR_SKIP", name, "local-missing")
        return 0

    local = json.loads(path.read_text(encoding="utf-8"))
    source_by_id = index_stories(source)
    local_by_id = index_stories(local)
    repaired = 0

    for story_id, local_story in local_by_id.items():
        source_story = source_by_id.get(story_id)
        if not source_story:
            continue
        story_changed = False
        for field in CORE_FIELDS:
            source_text = source_story.get(field)
            if not isinstance(source_text, str) or not source_text.strip():
                continue
            current = local_story.get(field)
            strict = field in integrity.PROSE_FIELDS
            if not bad_translation(source_text, current, strict):
                continue
            print(
                "CORE_TARGET_REPAIR_FIELD",
                f"file={name}",
                f"id={story_id}",
                f"field={field}",
                f"old={str(current or '')[:90]!r}",
            )
            value = repair_value(source_text, strict)
            if bad_translation(source_text, value, strict):
                raise RuntimeError(
                    f"Core targeted repair still failed quality: {name}:{story_id}:{field}"
                )
            local_story[field] = value
            repaired += 1
            story_changed = True

        if story_changed:
            # Furigana is rebuilt below for the whole small core file so visible
            # ruby never preserves text from the poisoned pre-repair field.
            local_story.pop("furigana", None)

    if repaired:
        if name == "latest.json":
            local = base.add_furigana(base.attach_daily_audio(local), "articles")
        elif name == "live.json":
            local = base.add_furigana(base.attach_live_audio(local), "items")
        path.write_text(
            json.dumps(local, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print("CORE_TARGET_REPAIR_RESULT", name, f"fields={repaired}")
    return repaired


def main():
    base.likely_chinese_source = extra.needs_cantonese_translation
    base.TRANSLATE_KEYS.update({"impactLabel"})
    furigana_safe_runtime.install()
    metadata_overrides.install(runtime)
    runtime.install()
    safe.prune_cache()

    total = 0
    for name in CORE_FILES:
        source = snapshot.load_json(name)
        total += repair_file(name, source)

    runtime.checkpoint_cache("targeted-core-repair")
    print(
        "CORE_TARGET_REPAIR_OK",
        f"fields={total}",
        f"snapshot={snapshot.snapshot_commit()}",
    )


if __name__ == "__main__":
    main()
