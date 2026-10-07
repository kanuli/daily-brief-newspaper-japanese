#!/usr/bin/env python3
"""Fast exhaustive source-aware repair without loading the local ML model."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import cantonese_snapshot as snapshot
import furigana_safe_runtime
import newsroom_quality
import safe_sync as safe
import sync_and_translate as base
import sync_cantonese_layers as extra
import validate_content_integrity as integrity

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TRANSLATE_KEYS = set(base.TRANSLATE_KEYS) | {"impactLabel", "sectionLabel"}

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


def bad(source: str, target: str, strict: bool, field: str = "") -> bool:
    if not isinstance(target, str) or not target.strip():
        return True
    if not safe.target_quality_ok(source, target, strict=strict):
        return True
    if newsroom_quality.hard_reason(source, target, field):
        return True
    return obvious_bad(target)


def remote_translate(source: str, strict: bool, field: str = "") -> str:
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
            value = newsroom_quality.deterministic_postedit(source, value, field)
            if not bad(source, value, strict, field):
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
                    polished = newsroom_quality.deterministic_postedit(source_child, local_child, key)
                    if polished != local_child and not bad(source_child, polished, strict, key):
                        lv[key] = polished
                        local_child = polished
                        repaired += 1
                        story_changed = True
                    if bad(source_child, local_child, strict, key):
                        print(
                            "REMOTE_FULL_REPAIR_FIELD",
                            f"file={name}",
                            f"key={key}",
                            f"old={local_child[:100]!r}",
                        )
                        lv[key] = remote_translate(source_child, strict, key)
                        repaired += 1
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



def iter_story_dicts(value):
    if extra.story_like(value):
        yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from iter_story_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_story_dicts(child)


def index_story_dicts(value):
    return {
        str(story.get("id")): story
        for story in iter_story_dicts(value)
        if story.get("id")
    }


def finalize_clean_metadata(name: str) -> None:
    """Clear degraded markers only after every source-linked field is healthy."""
    path = DATA / name
    if not path.is_file():
        return
    source = source_for(name)
    if source is None:
        return
    local = json.loads(path.read_text(encoding="utf-8"))
    source_by_id = index_story_dicts(source)
    failures = []

    for story in iter_story_dicts(local):
        story_id = str(story.get("id") or "")
        source_story = source_by_id.get(story_id)
        status = str(story.get("translationStatus") or "").strip().upper()
        if not source_story:
            if status in {"EDITORIAL_MINIMUM_FALLBACK", "TRANSLATION_FAILED", "TRANSLATION_DEGRADED"}:
                failures.append(f"{name}:{story_id}:unmatched-{status}")
            continue

        for field in TRANSLATE_KEYS:
            source_text = source_story.get(field)
            target_text = story.get(field)
            if not isinstance(source_text, str) or not source_text.strip():
                continue
            if not isinstance(target_text, str):
                failures.append(f"{name}:{story_id}:{field}:missing")
                continue
            strict = field in integrity.PROSE_FIELDS
            if bad(source_text, target_text, strict, field):
                failures.append(f"{name}:{story_id}:{field}:rejected")

        if status in {"EDITORIAL_MINIMUM_FALLBACK", "TRANSLATION_FAILED", "TRANSLATION_DEGRADED"}:
            story.pop("translationStatus", None)

    if failures:
        raise RuntimeError(
            "Rolling recovery cannot clear degraded metadata; "
            + ", ".join(failures[:40])
        )

    local["translationDegraded"] = False
    local["translationDeferredCount"] = 0
    local["translationDeferredIds"] = []
    if "translationDeferredMetadata" in local:
        local["translationDeferredMetadata"] = []
    path.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("REMOTE_FULL_DEGRADED_MARKERS_CLEARED", name)

def source_for(name: str):
    return snapshot.load_json(name, optional=name.startswith("topic-more/"))


def payload_stamp(payload):
    if not isinstance(payload, dict):
        return None
    for key in ("generatedAt", "lastUpdated", "sourceGeneratedAt", "checkedAt"):
        value = payload.get(key)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def minimum_rolling_source(name: str, source: dict) -> dict:
    """Keep a small current source-backed edition for remote fallback recovery."""
    if not isinstance(source, dict):
        return source

    copy = dict(source)
    if name == "desk-latest.json" and isinstance(source.get("desks"), dict):
        desks = {}
        for desk, rows in source["desks"].items():
            selected = list(rows) if isinstance(rows, list) else []
            desks[str(desk)] = selected[:1]
        copy["desks"] = desks
        copy["editorSelectionMode"] = "remote-minimum-guaranteed-edition-per-desk"
    elif name == "stocks-latest.json" and isinstance(source.get("tickers"), dict):
        tickers = {}
        for ticker, info in source["tickers"].items():
            if not isinstance(info, dict):
                tickers[ticker] = info
                continue
            item = dict(info)
            rows = list(info.get("stories") or []) if isinstance(info.get("stories"), list) else []
            item["stories"] = rows[:1]
            tickers[ticker] = item
        copy["tickers"] = tickers
        copy["editorSelectionMode"] = "remote-minimum-guaranteed-edition-per-ticker"
    return copy


def refresh_stale_static_rolling(name: str) -> bool:
    """Rebuild stale Desk/Stocks from the frozen fresh source before post-editing.

    The old exhaustive path only edited fields already present in the Japanese
    file. That could never advance generatedAt/source structure after the
    Cantonese source changed, so NAS kept seeing the same stale layer forever.
    """
    if name not in {"desk-latest.json", "stocks-latest.json"}:
        return False

    source = source_for(name)
    if not isinstance(source, dict):
        return False
    path = DATA / name
    try:
        local = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except Exception:
        local = {}

    source_ts = payload_stamp(source)
    local_ts = payload_stamp(local)
    if source_ts is None:
        raise RuntimeError(f"{name}: source timestamp missing")
    if local_ts is not None and local_ts >= source_ts:
        return False

    prepared = minimum_rolling_source(name, source)
    base.likely_chinese_source = extra.needs_cantonese_translation
    base.TRANSLATE_KEYS.update({"impactLabel", "sectionLabel"})
    safe.prune_cache()
    translated = safe.safe_convert(prepared)
    extra.decorate_story_tree(translated, "rolling")
    if not isinstance(translated, dict):
        raise RuntimeError(f"{name}: translated payload is not an object")

    translated["language"] = "ja"
    translated["translationSource"] = "kanuli/daily-brief-newspaper"
    translated["sourceFile"] = name
    translated["sourceFingerprint"] = extra.fingerprint(prepared)
    translated["translationSchemaVersion"] = extra.SCHEMA
    translated["sourceParityMode"] = "remote-minimum-source-refresh-v1"
    translated["translationDegraded"] = False
    translated["translationDeferredCount"] = 0
    translated["translationDeferredIds"] = []
    translated["translationDeferredMetadata"] = []

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(translated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "REMOTE_FULL_SOURCE_REFRESH_OK",
        f"file={name}",
        f"source={source_ts.isoformat()}",
        f"previous={local_ts.isoformat() if local_ts else 'missing'}",
    )
    return True


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
    """A failed rolling post-edit cannot block other healthy reader layers."""
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
    isolated_failures = []
    if scope in {"all", "core"}:
        # Daily/Live remain fail-closed.
        total += repair_file("latest.json", "daily")
        total += repair_file("live.json", "live")

    if scope in {"all", "rolling"}:
        names = ["desk-latest.json", "stocks-latest.json"]
        latest = snapshot.load_json("latest.json") or {}
        date = str(latest.get("date") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            names.append(f"topic-more/{date}.json")
        for name in names:
            refresh_ok = True
            if name in {"desk-latest.json", "stocks-latest.json"}:
                try:
                    refresh_stale_static_rolling(name)
                except Exception as exc:
                    refresh_ok = False
                    print(
                        "REMOTE_FULL_SOURCE_REFRESH_FAILED",
                        f"file={name}",
                        f"error={type(exc).__name__}:{str(exc)[:500]}",
                    )
            count, ok = repair_rolling_file_isolated(name)
            ok = ok and refresh_ok
            total += count
            if ok:
                try:
                    finalize_clean_metadata(name)
                except Exception as exc:
                    ok = False
                    print(
                        "REMOTE_FULL_METADATA_FINALIZE_FAILED",
                        f"file={name}",
                        f"error={type(exc).__name__}:{str(exc)[:500]}",
                    )
            if not ok:
                isolated_failures.append(name)

    print(
        "REMOTE_FULL_PUBLISHED_QUALITY_REPAIR_OK",
        f"scope={scope}",
        f"fields={total}",
        f"isolated_failures={','.join(isolated_failures) if isolated_failures else 'none'}",
        f"furigana_engine={furigana_safe_runtime.engine_name()}",
        "newsroom_quality=true",
        "rolling_validation_remains_authoritative=true",
    )


if __name__ == "__main__":
    main()
