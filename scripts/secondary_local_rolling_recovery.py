#!/usr/bin/env python3
"""Fail-closed, local-only refresh of the existing minimum rolling edition.

Reuse Japanese Core text only when its *whole frozen source fingerprint*
matches this run's immutable source and the individual field passes the same
source-aware gates again. Missing/rejected fields use the already reviewed
independent M2M100 translator, not OPUS or hosted translation APIs. Never edit
Core data, source timestamps, story IDs, source links, or publication markers.
The existing workflow must still run rolling integrity/editorial/freshness
gates, publish normally, and return control to the NAS Editor-in-Chief.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path

import cantonese_snapshot as snapshot
import fast_safe_sync as fast
import furigana_safe_runtime
import newsroom_quality
import run_extra_sync_editor as editor
import safe_sync as safe
import sync_and_translate as base
import sync_cantonese_layers as extra
import validate_content_integrity as integrity

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_REPOSITORY = "kanuli/daily-brief-newspaper"
BAD_STATUSES = {"EDITORIAL_MINIMUM_FALLBACK", "TRANSLATION_FAILED", "TRANSLATION_DEGRADED"}
TEXT_KEYS = set(base.TRANSLATE_KEYS) | {"impactLabel", "sectionLabel"}
SEED_FIELDS = set(integrity.STORY_TEXT_FIELDS) | {"section", "sectionLabel"}
# Legacy Core payloads can retain generic availability prose even after their
# status marker was cleared. Such text must never seed a successful translation.
FALLBACK_COPY_RE = re.compile(
    r"(?:完全な日本語本文|詳細な日本語本文|翻訳サービスの一時的な制限|"
    r"自動復旧処理で(?:順次)?更新|出典で確認済みの最新情報を先行掲載)"
)
CALENDAR_LABEL_RE = re.compile(
    r"\d{4}年\d{1,2}月\d{1,2}日(?: \d{1,2}:\d{2}(?: (?:HKT|UTC|JST))?)?"
)


def atomic_json(path: Path, value) -> None:
    """Replace one validated file; a failed write leaves the old file intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def cache_key(source_text: str) -> str:
    return hashlib.sha256(f"{base.CACHE_VERSION}|{source_text}".encode("utf-8")).hexdigest()


def checkpoint_cache(label: str) -> None:
    atomic_json(base.CACHE_PATH, base.CACHE)
    print("ROLLING_LOCAL_CACHE_CHECKPOINT", label, f"entries={len(base.CACHE)}")


def valid_field(source_text, target_text, field: str) -> bool:
    if not isinstance(target_text, str) or not target_text.strip():
        return False
    if FALLBACK_COPY_RE.search(target_text):
        return False
    strict = field in integrity.PROSE_FIELDS or field in safe.STRICT_PROSE_KEYS
    return bool(
        safe.target_quality_ok(source_text, target_text, strict=strict)
        and not newsroom_quality.hard_reason(source_text, target_text, field)
    )


def iter_stories(value):
    if extra.story_like(value):
        yield value
    if isinstance(value, dict):
        for key, child in value.items():
            if key != "furigana":
                yield from iter_stories(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_stories(child)


def seed_core_file(name: str, source: dict, japanese: dict) -> int:
    """Cache only revalidated fields with exact frozen-source provenance."""
    if not isinstance(source, dict) or not isinstance(japanese, dict):
        return 0
    if (
        japanese.get("language") != "ja"
        or japanese.get("translationSource") != SOURCE_REPOSITORY
        or japanese.get("sourceFile") != name
        or japanese.get("sourceFingerprint") != extra.fingerprint(source)
        or japanese.get("translationDegraded")
        or int(japanese.get("translationDeferredCount") or 0) != 0
        or japanese.get("translationDeferredIds")
        or japanese.get("translationDeferredMetadata")
    ):
        print("ROLLING_CORE_SEED_REJECT", name, "reason=source-or-state-mismatch")
        return 0
    japanese_by_id = {str(story["id"]): story for story in iter_stories(japanese)}
    seeded = 0
    for story in iter_stories(source):
        target = japanese_by_id.get(str(story["id"]))
        if not isinstance(target, dict):
            continue
        if str(target.get("translationStatus") or "").upper() in BAD_STATUSES:
            continue
        # Whole-source matching is required above; ID and source URL bind this
        # target to the correct owner, not just a similarly shaped story.
        if target.get("sourceUrl") != story.get("sourceUrl"):
            continue
        for field in SEED_FIELDS:
            source_text = story.get(field)
            if not isinstance(source_text, str) or not source_text.strip():
                continue
            target_text = target.get(field)
            if valid_field(source_text, target_text, field):
                base.CACHE[cache_key(source_text)] = target_text
                seeded += 1
    print("ROLLING_CORE_SEED_OK", name, f"fields={seeded}")
    return seeded


def seed_current_core() -> int:
    total = 0
    for name in ("latest.json", "live.json"):
        path = DATA / name
        if not path.is_file():
            continue
        source = snapshot.load_json(name)
        japanese = json.loads(path.read_text(encoding="utf-8"))
        total += seed_core_file(name, source, japanese)
    checkpoint_cache("revalidated-core")
    return total


def translate_field(source_text: str, field: str) -> str:
    if not source_text.strip() or re.match(r"^https?://", source_text):
        return source_text
    if safe.bad_error_text(source_text):
        raise RuntimeError(f"Refusing upstream error payload in {field}")
    key = cache_key(source_text)
    cached = base.CACHE.get(key)
    if valid_field(source_text, cached, field):
        return cached
    base.CACHE.pop(key, None)

    # Fixed chrome/category localization is not a translation API. Preserve all
    # numeric anchors through the normal source-aware gate before caching it.
    deterministic = fast.localize_non_chinese(source_text)
    if (
        (
            deterministic != source_text
            or not re.search(r"[\u3400-\u9fff]", source_text)
            or (
                field in {"timeLabel", "lastUpdatedLabel"}
                and CALENDAR_LABEL_RE.fullmatch(source_text)
            )
        )
        and valid_field(source_text, deterministic, field)
    ):
        candidate = deterministic
    else:
        # Lazy import: fully cached desks do not load a second model at all.
        import secondary_local_core_recovery as secondary
        strict = field in integrity.PROSE_FIELDS or field in safe.STRICT_PROSE_KEYS
        candidate = secondary.translate(source_text, strict, field)
    candidate = newsroom_quality.deterministic_postedit(source_text, candidate, field)
    if not valid_field(source_text, candidate, field):
        raise RuntimeError(f"Local rolling recovery rejected final {field}")
    base.CACHE[key] = candidate
    checkpoint_cache(f"field-{field}")
    return candidate


def convert_tree(source, parent_key=""):
    """Build from current source, not old targets; untouched metadata is exact."""
    if isinstance(source, list):
        return [convert_tree(child, parent_key) for child in source]
    if isinstance(source, dict):
        output = {}
        for key, value in source.items():
            if key in base.KEEP_KEYS or key == "furigana":
                output[key] = deepcopy(value)
            else:
                output[key] = convert_tree(value, key)
        return output
    if isinstance(source, str) and parent_key in TEXT_KEYS:
        return translate_field(source, parent_key)
    return deepcopy(source)


def verify_tree(source, target, parent_key="", path="$") -> None:
    """Check all fields/structure before adding generated Japanese metadata."""
    if isinstance(source, dict):
        if not isinstance(target, dict) or set(source) != set(target):
            raise RuntimeError(f"Source structure mismatch at {path}")
        for key, value in source.items():
            if key in base.KEEP_KEYS or key == "furigana":
                if target[key] != value:
                    raise RuntimeError(f"Source identity changed at {path}.{key}")
            else:
                verify_tree(value, target[key], key, f"{path}.{key}")
    elif isinstance(source, list):
        if not isinstance(target, list) or len(source) != len(target):
            raise RuntimeError(f"Source list mismatch at {path}")
        for index, (left, right) in enumerate(zip(source, target)):
            verify_tree(left, right, parent_key, f"{path}[{index}]")
    elif isinstance(source, str) and parent_key in TEXT_KEYS and source.strip():
        if not re.match(r"^https?://", source) and not valid_field(source, target, parent_key):
            raise RuntimeError(f"Source-aware field check failed at {path}")
    elif source != target:
        raise RuntimeError(f"Source metadata changed at {path}")


def recover_file(name: str, source: dict) -> int:
    # Same existing editorial selection policy; no new ranking or source fetch.
    prepared = editor._prepare_source(name, source)
    translated = convert_tree(prepared)
    verify_tree(prepared, translated)
    if not isinstance(translated, dict):
        raise RuntimeError(f"Invalid rolling object: {name}")
    source_count = sum(1 for _ in iter_stories(prepared))
    if name in {"desk-latest.json", "stocks-latest.json"} and not source_count:
        raise RuntimeError(f"Refusing empty rolling publication: {name}")
    extra.decorate_story_tree(translated, "rolling")
    translated.update({
        "language": "ja", "translationSource": SOURCE_REPOSITORY,
        "sourceFile": name, "sourceFingerprint": extra.fingerprint(prepared),
        "translationSchemaVersion": extra.SCHEMA,
        "sourceParityMode": "local-minimum-source-refresh-v1",
        "translationDegraded": False, "translationDeferredCount": 0,
        "translationDeferredIds": [], "translationDeferredMetadata": [],
        "translationRecoveryMode": "m2m100-current-source-minimum-v1",
        "furiganaEngineVersion": furigana_safe_runtime.engine_name(),
    })
    # Each layer's reader data replaces the old file only after full validation.
    atomic_json(DATA / name, translated)
    checkpoint_cache(f"file-{name.replace('/', '-')}")
    print("ROLLING_LOCAL_SOURCE_REFRESH_OK", name, f"stories={source_count}",
          "remote_translation_api=false", "degraded=false")
    return source_count


def main() -> int:
    base.likely_chinese_source = extra.needs_cantonese_translation
    newsroom_quality.install(safe)
    furigana_safe_runtime.install()
    safe.prune_cache()
    seed_current_core()
    latest = snapshot.load_json("latest.json")
    desk = snapshot.load_json("desk-latest.json")
    day = str(desk.get("date") or latest.get("date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise RuntimeError("Invalid frozen source date")
    scope, names = editor._selected_names(f"topic-more/{day}.json")
    for name in names:
        source = snapshot.load_json(name, optional=name.startswith("topic-more/"))
        if source is not None:
            recover_file(name, source)
    # No remote dispatch/publish and no topic deletion here. Workflow gates and
    # the NAS Editor-in-Chief remain the sole publication/recovery authority.
    print("ROLLING_LOCAL_RECOVERY_COMPLETE", f"scope={scope}",
          f"snapshot={snapshot.snapshot_commit()}", "workflow_validation_required=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
