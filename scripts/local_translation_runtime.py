#!/usr/bin/env python3
"""Install the local OPUS-MT translator into the existing Japanese pipeline."""
from __future__ import annotations

import hashlib
import json
import re

import fast_safe_sync as fast
import local_zh_ja
import safe_sync as safe
import sync_and_translate as base

TEXT_PART_LIMIT = 280
OWNER_BATCH_SIZE = 4
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?])")


def cache_key(text: str) -> str:
    return hashlib.sha256(f"{base.CACHE_VERSION}|{text}".encode("utf-8")).hexdigest()


def checkpoint_cache(label: str) -> None:
    base.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    base.CACHE_PATH.write_text(
        json.dumps(base.CACHE, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"LOCAL_MT_CACHE_CHECKPOINT {label} entries={len(base.CACHE)}")


def _retry_quality_failure(text: str, first_value: str, strict=False) -> str:
    """Retry one bad item locally instead of failing its whole owner batch."""
    print(
        "LOCAL_MT_RETRY_QUALITY",
        f"source={text[:80]!r}",
        f"first={str(first_value or '')[:80]!r}",
    )

    # Pass 2: normalize Traditional Chinese to Simplified locally and decode the
    # single item with a wider beam. OPUS training is substantially richer in
    # standardized Chinese than in Cantonese-specific Traditional variants.
    retry = local_zh_ja.translate_one(
        text,
        normalize_traditional=True,
        num_beams=6,
    )
    if safe.target_quality_ok(text, retry, strict=strict):
        print("LOCAL_MT_RETRY_OK mode=t2s-single")
        return retry

    # Pass 3: for compound prose, translate sentence-sized units separately.
    # This keeps one difficult clause from poisoning the entire paragraph.
    pieces = [x for x in _SENTENCE_SPLIT_RE.split(text) if x]
    if len(pieces) > 1:
        values = local_zh_ja.translate_many(
            pieces,
            batch_size=1,
            normalize_traditional=True,
            num_beams=6,
        )
        combined = "".join(values)
        if safe.target_quality_ok(text, combined, strict=strict):
            print(f"LOCAL_MT_RETRY_OK mode=t2s-sentences parts={len(pieces)}")
            return combined

    raise RuntimeError(
        "Local OPUS-MT quality gate failed after isolated local retries: "
        f"source={text[:100]!r}; first={str(first_value or '')[:100]!r}; "
        f"retry={str(retry or '')[:100]!r}"
    )


def _validated_translation(text: str, value: str, strict=False) -> str:
    if safe.target_quality_ok(text, value, strict=strict):
        return value
    return _retry_quality_failure(text, value, strict=strict)


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
            translated = _validated_translation(source_part, translated, strict=False)
            resolved[index] = translated
            base.CACHE[cache_key(source_part)] = translated
        checkpoint_cache(f"parts-{start + len(batch_texts)}-of-{len(missing_texts)}")

    result = "".join(x or "" for x in resolved)
    result = _validated_translation(value, result, strict=strict)
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
        value = _validated_translation(text, value, strict=strict)
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
