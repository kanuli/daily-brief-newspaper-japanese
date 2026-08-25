#!/usr/bin/env python3
"""Install the local OPUS-MT translator into the existing Japanese pipeline."""
from __future__ import annotations

import hashlib
import json

import fast_safe_sync as fast
import local_zh_ja
import safe_sync as safe
import sync_and_translate as base

TEXT_PART_LIMIT = 280
OWNER_BATCH_SIZE = 4


def cache_key(text: str) -> str:
    return hashlib.sha256(f"{base.CACHE_VERSION}|{text}".encode("utf-8")).hexdigest()


def checkpoint_cache(label: str) -> None:
    base.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    base.CACHE_PATH.write_text(
        json.dumps(base.CACHE, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"LOCAL_MT_CACHE_CHECKPOINT {label} entries={len(base.CACHE)}")


def localize_or_translate(text: str, strict=False) -> str:
    value = str(text or "")
    if not base.likely_chinese_source(value):
        result = fast.localize_non_chinese(value)
        if not safe.target_quality_ok(value, result, strict=strict):
            raise RuntimeError(f"Local normalization failed: {value[:100]!r}")
        return result

    full_key = cache_key(value)
    cached = base.CACHE.get(full_key)
    if cached is not None and safe.target_quality_ok(value, cached, strict=strict):
        return cached

    parts = base.chunks(value, limit=TEXT_PART_LIMIT) or [value]
    resolved: list[str | None] = [None] * len(parts)
    missing_indexes = []
    missing_texts = []
    for index, part in enumerate(parts):
        if not part.strip():
            resolved[index] = part
            continue
        part_cached = base.CACHE.get(cache_key(part))
        if part_cached is not None and safe.target_quality_ok(part, part_cached, strict=False):
            resolved[index] = part_cached
            continue
        missing_indexes.append(index)
        missing_texts.append(part)

    for start in range(0, len(missing_texts), OWNER_BATCH_SIZE):
        batch_texts = missing_texts[start : start + OWNER_BATCH_SIZE]
        batch_indexes = missing_indexes[start : start + OWNER_BATCH_SIZE]
        outputs = local_zh_ja.translate_many(batch_texts, batch_size=OWNER_BATCH_SIZE)
        if len(outputs) != len(batch_texts):
            raise RuntimeError("Local OPUS-MT returned wrong batch size")
        for source_part, index, translated in zip(batch_texts, batch_indexes, outputs):
            if not safe.target_quality_ok(source_part, translated, strict=False):
                raise RuntimeError(f"Local OPUS-MT part quality gate failed: {source_part[:100]!r}")
            resolved[index] = translated
            base.CACHE[cache_key(source_part)] = translated

    result = "".join(x or "" for x in resolved)
    if not safe.target_quality_ok(value, result, strict=strict):
        raise RuntimeError(f"Local OPUS-MT quality gate failed: {value[:100]!r}")
    base.CACHE[full_key] = result
    return result


def local_translate_part(part, strict=False):
    return localize_or_translate(str(part or ""), strict=strict)


def _translate_short_group(group):
    source_texts = [text for text, _strict in group]
    outputs = local_zh_ja.translate_many(source_texts, batch_size=OWNER_BATCH_SIZE)
    if len(outputs) != len(group):
        raise RuntimeError("Local OPUS-MT returned wrong owner batch size")
    for (text, strict), value in zip(group, outputs):
        if not safe.target_quality_ok(text, value, strict=strict):
            raise RuntimeError(f"Local OPUS-MT quality gate failed: {text[:100]!r}")
        base.CACHE[cache_key(text)] = value


def local_prewarm_translations(source, label):
    """Translate only missing source text, saving progress after every small batch."""
    candidates = fast.collect_translatable(source)
    pending = []
    local_count = 0
    cached_count = 0
    for text, strict in candidates.items():
        cached = base.CACHE.get(cache_key(text))
        if cached is not None and safe.target_quality_ok(text, cached, strict=strict):
            cached_count += 1
            continue
        if not base.likely_chinese_source(text):
            base.CACHE[cache_key(text)] = localize_or_translate(text, strict=strict)
            local_count += 1
            continue
        pending.append((text, strict))

    checkpoint_cache(f"{label}-seed")
    print(
        f"LOCAL_MT_PREWARM {label}: pending={len(pending)} cached={cached_count} "
        f"local={local_count} owner_batch={OWNER_BATCH_SIZE} part_limit={TEXT_PART_LIMIT}"
    )
    if not pending:
        return

    short_group = []
    completed = 0

    def flush_short_group():
        nonlocal short_group, completed
        if not short_group:
            return
        _translate_short_group(short_group)
        completed += len(short_group)
        checkpoint_cache(f"{label}-{completed}-of-{len(pending)}")
        short_group = []

    for text, strict in pending:
        if len(text) <= TEXT_PART_LIMIT:
            short_group.append((text, strict))
            if len(short_group) >= OWNER_BATCH_SIZE:
                flush_short_group()
            continue

        flush_short_group()
        localize_or_translate(text, strict=strict)
        completed += 1
        checkpoint_cache(f"{label}-{completed}-of-{len(pending)}")

    flush_short_group()
    print(f"LOCAL_MT_PREWARM_OK {label}: translated={completed}")


def install():
    """Replace every production translation hook with local OPUS-MT."""
    fast.bounded_gtx = local_translate_part
    fast.bounded_mymemory = local_translate_part
    fast.bounded_translate_part = local_translate_part
    fast.prewarm_translations = local_prewarm_translations

    def installer():
        # Legacy function names are intentionally rebound so no production path
        # can call Google or MyMemory even if older conversion code invokes them.
        safe.google_gtx_translate = local_translate_part
        safe.google_translate = local_translate_part
        safe.mymemory_translate = local_translate_part
        safe.safe_translate_part = local_translate_part
        base.translate_part = lambda part: local_translate_part(part, strict=False)

    fast.install_bounded_translator = installer
    installer()
    print("LOCAL_MT_RUNTIME_INSTALLED remote_translation_calls=disabled model=Helsinki-NLP/opus-mt-tc-big-zh-ja")
