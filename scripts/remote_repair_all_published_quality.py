#!/usr/bin/env python3
"""Repair already-published Japanese prose with remote translation fallbacks.

Core Daily/Live repair is fail-closed. Rolling/category repair is deliberately
file-isolated: a stale or rate-limited stock layer must never prevent a healthy
current desk/topic candidate from reaching the publication validator. The
validator remains the final authority on what is reader-publishable.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests

import cantonese_snapshot as snapshot
import furigana_safe_runtime
import newsroom_quality
import safe_sync as safe
import sync_and_translate as base

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROSE_FIELDS = ("title", "dek", "summary", "body", "context", "why", "watchNext")
VISIBLE_FIELDS = PROSE_FIELDS + ("section", "impactLabel", "lastUpdatedLabel", "subtitle", "tagline")


def _valid_japanese(value: str, strict: bool) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if safe.translation_failed(text):
        return False
    if safe.garbled_japanese_reason(text, strict=strict):
        return False
    if strict and safe.prose_is_mixed(text):
        return False
    return True


def _google_translate(text: str) -> str:
    response = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "zh-CN", "tl": "ja", "dt": "t", "q": text},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return "".join(str(row[0]) for row in (payload[0] or []) if row and row[0]).strip()


def _mymemory_translate(text: str) -> str:
    response = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text, "langpair": "zh-CN|ja"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return str((payload.get("responseData") or {}).get("translatedText") or "").strip()


def remote_translate(text: str, strict: bool, key: str) -> str:
    errors = []
    for name, fn in (("gtx", _google_translate), ("google", _google_translate), ("mymemory", _mymemory_translate)):
        try:
            translated = fn(text)
            if not _valid_japanese(translated, strict):
                raise RuntimeError(f"{name} returned invalid/non-Japanese translator payload")
            print("REMOTE_FULL_REPAIR_OK", name, repr(text[:80]), "->", repr(translated[:80]))
            return translated
        except Exception as exc:
            errors.append(f"{name}={type(exc).__name__}:{exc}")
    raise RuntimeError("All remote repair backends failed: " + "; ".join(errors))


def _story_like(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and bool(value.get("id"))
        and isinstance(value.get("title"), str)
        and bool(value.get("title"))
        and any(value.get(k) for k in ("dek", "summary", "body"))
    )


def repair_tree(local, source, name: str, story_mode: str) -> int:
    repaired = 0

    def walk(lv, sv, current_story=None):
        nonlocal repaired
        any_changed = False
        if _story_like(lv):
            current_story = lv

        if isinstance(lv, dict) and isinstance(sv, dict):
            for key, source_child in sv.items():
                if key not in lv:
                    continue
                local_child = lv[key]
                if isinstance(source_child, str) and isinstance(local_child, str) and key in VISIBLE_FIELDS:
                    strict = key in PROSE_FIELDS
                    if strict and not safe.prose_is_mixed(local_child) and not safe.garbled_japanese_reason(local_child, strict=True):
                        continue
                    if not strict and not safe.translation_failed(local_child) and not safe.garbled_japanese_reason(local_child, strict=False):
                        continue
                    print("REMOTE_FULL_REPAIR_FIELD", f"file={name}", f"key={key}", f"old={local_child[:120]!r}")
                    lv[key] = remote_translate(source_child, strict, key)
                    repaired += 1
                    any_changed = True
                elif isinstance(local_child, (dict, list)) and isinstance(source_child, type(local_child)):
                    if walk(local_child, source_child, current_story):
                        any_changed = True
            if current_story is lv and any_changed:
                # Re-render learner-facing ruby only for a changed story.
                base.render_story_furigana(lv)
            return any_changed

        if isinstance(lv, list) and isinstance(sv, list):
            # Align story lists by id where possible; positional alignment is unsafe
            # once rolling self-healing has quarantined/deferred individual items.
            source_by_id = {
                str(item.get("id")): item
                for item in sv
                if isinstance(item, dict) and item.get("id")
            }
            for index, local_item in enumerate(lv):
                source_item = None
                if isinstance(local_item, dict) and local_item.get("id"):
                    source_item = source_by_id.get(str(local_item.get("id")))
                elif index < len(sv):
                    source_item = sv[index]
                if source_item is not None and isinstance(local_item, type(source_item)):
                    any_changed = walk(local_item, source_item, current_story) or any_changed
            return any_changed
        return False

    walk(local, source)
    # Daily/Live always migrate ruby to the current lexical engine even when the
    # Japanese prose itself did not need a field repair.
    if story_mode == "daily":
        base.add_furigana(base.attach_daily_audio(local), "articles")
        local["furiganaEngineVersion"] = furigana_safe_runtime.engine_name()
        local["newsroomQualityVersion"] = 1
    elif story_mode == "live":
        base.add_furigana(base.attach_live_audio(local), "items")
        local["furiganaEngineVersion"] = furigana_safe_runtime.engine_name()
        local["newsroomQualityVersion"] = 1
    return repaired


def source_for(name: str):
    return snapshot.load_json(name, optional=name.startswith("topic-more/"))


def repair_file(name: str, mode: str) -> int:
    path = DATA / name
    if not path.is_file():
        return 0
    source = source_for(name)
    if source is None:
        return 0
    local = json.loads(path.read_text(encoding="utf-8"))
    before = json.dumps(local, ensure_ascii=False, sort_keys=True)
    count = repair_tree(local, source, name, mode)
    after = json.dumps(local, ensure_ascii=False, sort_keys=True)
    if before != after:
        path.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("REMOTE_FULL_REPAIR_RESULT", name, f"fields={count}", f"rerendered={str(before != after).lower()}")
    return count


def repair_rolling_file_isolated(name: str) -> tuple[int, bool]:
    """Best-effort post-edit; validation decides whether the layer can publish."""
    try:
        return repair_file(name, "rolling"), True
    except Exception as exc:
        print(
            "REMOTE_FULL_REPAIR_FILE_FAILED_ISOLATED",
            f"file={name}",
            f"error={type(exc).__name__}:{str(exc)[:500]}",
        )
        return 0, False


def main():
    scope = str(os.environ.get("REMOTE_REPAIR_SCOPE") or "all").strip().lower()
    if scope not in {"all", "core", "rolling"}:
        raise RuntimeError(f"invalid REMOTE_REPAIR_SCOPE: {scope!r}")

    newsroom_quality.install(safe)
    furigana_safe_runtime.install()

    total = 0
    rolling_failures: list[str] = []
    if scope in {"all", "core"}:
        # Core remains fail-closed: these are the main Daily/Live publication.
        total += repair_file("latest.json", "daily")
        total += repair_file("live.json", "live")

    if scope in {"all", "rolling"}:
        names = ["desk-latest.json", "stocks-latest.json"]
        latest = snapshot.load_json("latest.json") or {}
        date = str(latest.get("date") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            names.append(f"topic-more/{date}.json")
        for name in names:
            count, ok = repair_rolling_file_isolated(name)
            total += count
            if not ok:
                rolling_failures.append(name)

    print(
        "REMOTE_FULL_PUBLISHED_QUALITY_REPAIR_OK",
        f"scope={scope}",
        f"fields={total}",
        f"isolated_failures={','.join(rolling_failures) if rolling_failures else 'none'}",
        f"furigana_engine={furigana_safe_runtime.engine_name()}",
        "newsroom_quality=true",
        "rolling_validation_remains_authoritative=true",
    )


if __name__ == "__main__":
    main()
