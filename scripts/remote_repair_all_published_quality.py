#!/usr/bin/env python3
"""Fast exhaustive source-aware repair without loading the local ML model."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import cantonese_snapshot as snapshot
import safe_sync as safe
import sync_and_translate as base
import sync_cantonese_layers as extra
import validate_content_integrity as integrity

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TRANSLATE_KEYS = set(base.TRANSLATE_KEYS) | {"impactLabel"}

REPEATED_PARTICLE_RE = re.compile(r"の{5,}")
REPEATED_TOKEN_RE = re.compile(r"(.{2,8})(?:\s+\1){2,}")
ASCII_ART_RE = re.compile(r"(?:━{4,}|─{5,}|═{5,}|[\\/@]{3,})")
CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
WEIRD_LOWER_RE = re.compile(r"(?<![A-Za-z])[a-z]{2,}(?![A-Za-z])")
LOWER_ALLOW = {"ai", "app", "apps", "web", "live", "online", "email", "vs", "km", "kg", "cm", "mm", "am", "pm"}


def obvious_bad(target: str) -> bool:
    text = str(target or "")
    if REPEATED_PARTICLE_RE.search(text) or REPEATED_TOKEN_RE.search(text):
        return True
    if ASCII_ART_RE.search(text) or CYRILLIC_RE.search(text):
        return True
    for match in WEIRD_LOWER_RE.finditer(text):
        if match.group(0).lower() not in LOWER_ALLOW:
            return True
    return False


def bad(source: str, target: str, strict: bool) -> bool:
    if not isinstance(target, str) or not target.strip():
        return True
    if not safe.target_quality_ok(source, target, strict=strict):
        return True
    return obvious_bad(target)


def remote_translate(source: str, strict: bool) -> str:
    errors = []
    backends = (
        ("gtx", safe.google_gtx_translate),
        ("google", safe.google_translate),
        ("mymemory", safe.mymemory_translate),
    )
    for label, fn in backends:
        if label == "mymemory" and not base.likely_chinese_source(source):
            continue
        try:
            value = fn(source, strict=strict)
            if not bad(source, value, strict):
                print("REMOTE_FULL_REPAIR_OK", label, repr(source[:70]), "->", repr(value[:70]))
                return value
            errors.append(f"{label}=enhanced-quality-rejected")
        except Exception as exc:
            errors.append(f"{label}={type(exc).__name__}:{exc}")
    raise RuntimeError("All remote repair backends failed: " + "; ".join(errors))


def list_key(value):
    if not isinstance(value, dict):
        return None
    for key in ("id", "slug", "ticker"):
        token = value.get(key)
        if isinstance(token, str) and token:
            return key, token
    return None


def repair_tree(local, source, name: str, story_mode: str) -> int:
    repaired = 0

    def walk(lv, sv, story=None):
        nonlocal repaired
        current_story = story
        if extra.story_like(lv) and extra.story_like(sv):
            current_story = lv
        story_changed = False

        if isinstance(lv, dict) and isinstance(sv, dict):
            for key, source_child in sv.items():
                if key not in lv:
                    continue
                local_child = lv[key]
                if (
                    key in TRANSLATE_KEYS
                    and isinstance(source_child, str)
                    and source_child.strip()
                    and isinstance(local_child, str)
                ):
                    strict = key in integrity.PROSE_FIELDS
                    if bad(source_child, local_child, strict):
                        print(
                            "REMOTE_FULL_REPAIR_FIELD",
                            f"file={name}",
                            f"key={key}",
                            f"old={local_child[:100]!r}",
                        )
                        lv[key] = remote_translate(source_child, strict)
                        repaired += 1
                        if current_story is lv:
                            story_changed = True
                elif isinstance(local_child, dict) and isinstance(source_child, dict):
                    if walk(local_child, source_child, current_story):
                        story_changed = True
                elif isinstance(local_child, list) and isinstance(source_child, list):
                    if walk(local_child, source_child, current_story):
                        story_changed = True

            if current_story is lv and story_changed and story_mode == "rolling":
                extra.decorate_story_tree(lv, "rolling")
            return story_changed

        if isinstance(lv, list) and isinstance(sv, list):
            source_index = {}
            for item in sv:
                key = list_key(item)
                if key:
                    source_index[key] = item
            any_changed = False
            for index, local_item in enumerate(lv):
                source_item = None
                key = list_key(local_item)
                if key and key in source_index:
                    source_item = source_index[key]
                elif index < len(sv):
                    source_item = sv[index]
                if source_item is None:
                    continue
                if isinstance(local_item, (dict, list)) and isinstance(source_item, type(local_item)):
                    any_changed = walk(local_item, source_item, current_story) or any_changed
            return any_changed
        return False

    walk(local, source)
    if repaired and story_mode == "daily":
        base.add_furigana(base.attach_daily_audio(local), "articles")
    elif repaired and story_mode == "live":
        base.add_furigana(base.attach_live_audio(local), "items")
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
    count = repair_tree(local, source, name, mode)
    if count:
        path.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("REMOTE_FULL_REPAIR_RESULT", name, f"fields={count}")
    return count


def main():
    scope = str(os.environ.get("REMOTE_REPAIR_SCOPE") or "all").strip().lower()
    if scope not in {"all", "core", "rolling"}:
        raise RuntimeError(f"invalid REMOTE_REPAIR_SCOPE: {scope!r}")

    total = 0
    if scope in {"all", "core"}:
        total += repair_file("latest.json", "daily")
        total += repair_file("live.json", "live")

    if scope in {"all", "rolling"}:
        total += repair_file("desk-latest.json", "rolling")
        total += repair_file("stocks-latest.json", "rolling")
        latest = snapshot.load_json("latest.json") or {}
        date = str(latest.get("date") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            total += repair_file(f"topic-more/{date}.json", "rolling")

    print("REMOTE_FULL_PUBLISHED_QUALITY_REPAIR_OK", f"scope={scope}", f"fields={total}")


if __name__ == "__main__":
    main()
