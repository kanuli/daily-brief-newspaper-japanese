#!/usr/bin/env python3
"""Install the local OPUS-MT translator into the existing Japanese pipeline.

The local model handles normal bulk work. A source field that still fails the
Japanese quality gate after isolated local retries is sent through the existing
free remote fallback chain one field at a time. This prevents one malformed
local decode from either poisoning publication data or aborting an entire
edition.
"""
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
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[，,；;：:])")
_TIME_LABEL_HINT_RE = re.compile(r"(?:HKT|UTC|JST|\bET\b|\d{1,2}月\d{1,2}日)", re.I)
_TIME_LABEL_STATUS_RE = re.compile(r"(?:發布|公布|核實|驗證|認證|截至|刊出|發稿|更新)")
_TIME_LABEL_REPLACEMENTS = (
    ("已核實", "確認済み"),
    ("前核實", "までに確認済み"),
    ("已驗證", "確認済み"),
    ("前驗證", "までに確認済み"),
    ("已認證", "確認済み"),
    ("前認證", "までに確認済み"),
    ("發布", "公開"),
    ("公布", "公表"),
    ("核實", "確認済み"),
    ("驗證", "確認済み"),
    ("認證", "確認済み"),
    ("截至", "時点"),
    ("刊出", "掲載"),
    ("發稿", "配信"),
)

# Capture the validated free fallbacks before install() rebinds production hooks
# to the local runtime. These are used ONLY for individual local quality failures.
_REMOTE_GTX = safe.google_gtx_translate
_REMOTE_GOOGLE = safe.google_translate
_REMOTE_MYMEMORY = safe.mymemory_translate


def cache_key(text: str) -> str:
    return hashlib.sha256(f"{base.CACHE_VERSION}|{text}".encode("utf-8")).hexdigest()


def checkpoint_cache(label: str) -> None:
    base.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    base.CACHE_PATH.write_text(
        json.dumps(base.CACHE, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"LOCAL_MT_CACHE_CHECKPOINT {label} entries={len(base.CACHE)}")


def deterministic_time_label(text: str) -> str | None:
    """Localize publication/verification metadata without sending it to MT.

    Short timestamp labels contain mostly digits, HKT and a few Cantonese status
    words. Marian can hallucinate badly on that shape, while the mapping itself
    is deterministic. Keep all numeric anchors unchanged and use Japanese
    punctuation so the Chinese-prose quality gate also remains meaningful.
    """
    value = str(text or "").strip()
    if not value or not _TIME_LABEL_HINT_RE.search(value) or not _TIME_LABEL_STATUS_RE.search(value):
        return None
    result = value
    for source, target in _TIME_LABEL_REPLACEMENTS:
        result = result.replace(source, target)
    result = result.replace("；", "・").replace("，", "、")
    result = re.sub(r"\s*・\s*", "・", result)
    result = re.sub(r"\s+", " ", result).strip()
    if not safe.target_quality_ok(value, result, strict=False):
        raise RuntimeError(f"Deterministic time-label localization failed: {value!r} -> {result!r}")
    print("LOCAL_MT_METADATA_LOCALIZED", f"source={value!r}", f"target={result!r}")
    return result


def _piecewise_retry(text: str, splitter: re.Pattern[str], mode: str, strict=False) -> str | None:
    pieces = [x for x in splitter.split(text) if x and x.strip()]
    if len(pieces) <= 1:
        return None

    translated: list[str] = []
    for index, piece in enumerate(pieces, 1):
        cached = base.CACHE.get(cache_key(piece))
        if cached is not None and safe.target_quality_ok(piece, cached, strict=False):
            value = cached
        else:
            value = local_zh_ja.translate_one(
                piece,
                normalize_traditional=True,
                num_beams=6,
            )
            if not safe.target_quality_ok(piece, value, strict=False):
                # Remove only terminal punctuation for one last local decode. This
                # helps Marian avoid rare empty generations on short mixed-name
                # clauses while preserving the source text in the quality check.
                bare = re.sub(r"[，,；;：:。！？!?]+$", "", piece).strip()
                if bare and bare != piece:
                    value = local_zh_ja.translate_one(
                        bare,
                        normalize_traditional=True,
                        num_beams=8,
                    )
            if not safe.target_quality_ok(piece, value, strict=False):
                print(
                    "LOCAL_MT_PIECE_FAILED",
                    f"mode={mode}",
                    f"part={index}/{len(pieces)}",
                    f"source={piece[:80]!r}",
                    f"output={str(value or '')[:80]!r}",
                )
                return None
            base.CACHE[cache_key(piece)] = value
            checkpoint_cache(f"retry-{mode}-{index}-of-{len(pieces)}")
        translated.append(value)

    combined = "".join(translated)
    if safe.target_quality_ok(text, combined, strict=strict):
        print(f"LOCAL_MT_RETRY_OK mode={mode} parts={len(pieces)}")
        return combined
    return None


def _remote_quality_fallback(text: str, strict=False) -> str:
    """Repair one rejected local result without turning bulk translation remote."""
    errors: list[str] = []
    backends = (
        ("gtx", _REMOTE_GTX),
        ("google", _REMOTE_GOOGLE),
        ("mymemory", _REMOTE_MYMEMORY),
    )
    for label, translator in backends:
        try:
            value = translator(text, strict=strict)
            if safe.target_quality_ok(text, value, strict=strict):
                print(
                    "LOCAL_MT_REMOTE_REPAIR_OK",
                    f"backend={label}",
                    f"source={text[:80]!r}",
                )
                base.CACHE[cache_key(text)] = value
                checkpoint_cache(f"remote-repair-{label}")
                return value
            errors.append(f"{label}=quality-rejected")
        except Exception as exc:
            errors.append(f"{label}={exc}")
    raise RuntimeError(
        "All validated repair backends failed for one rejected local field: "
        + "; ".join(errors)
    )


def _retry_quality_failure(text: str, first_value: str, strict=False) -> str:
    """Retry one bad item instead of failing or publishing its whole owner batch."""
    fixed = deterministic_time_label(text)
    if fixed is not None:
        return fixed

    print(
        "LOCAL_MT_RETRY_QUALITY",
        f"source={text[:80]!r}",
        f"first={str(first_value or '')[:80]!r}",
    )

    retry = local_zh_ja.translate_one(
        text,
        normalize_traditional=True,
        num_beams=6,
    )
    if safe.target_quality_ok(text, retry, strict=strict):
        print("LOCAL_MT_RETRY_OK mode=t2s-single")
        return retry

    sentence_value = _piecewise_retry(
        text,
        _SENTENCE_SPLIT_RE,
        "t2s-sentences",
        strict=strict,
    )
    if sentence_value is not None:
        return sentence_value

    # A single Chinese news sentence often contains two or more independent
    # clauses separated by full-width commas. Translate those clauses one at a
    # time when Marian returns a malformed complete-sentence decode.
    clause_value = _piecewise_retry(
        text,
        _CLAUSE_SPLIT_RE,
        "t2s-clauses",
        strict=strict,
    )
    if clause_value is not None:
        return clause_value

    print(
        "LOCAL_MT_LOCAL_RETRIES_EXHAUSTED",
        f"source={text[:80]!r}",
        f"retry={str(retry or '')[:80]!r}",
    )
    return _remote_quality_fallback(text, strict=strict)


def _validated_translation(text: str, value: str, strict=False) -> str:
    if safe.target_quality_ok(text, value, strict=strict):
        return value
    return _retry_quality_failure(text, value, strict=strict)


def localize_or_translate(text: str, strict=False) -> str:
    value = str(text or "")
    fixed = deterministic_time_label(value)
    if fixed is not None:
        base.CACHE[cache_key(value)] = fixed
        checkpoint_cache("deterministic-time-label")
        return fixed

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
        part_fixed = deterministic_time_label(part)
        if part_fixed is not None:
            resolved[index] = part_fixed
            base.CACHE[cache_key(part)] = part_fixed
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
            checkpoint_cache(f"part-item-{index + 1}-of-{len(parts)}")

    result = "".join(x or "" for x in resolved)
    result = _validated_translation(value, result, strict=strict)
    base.CACHE[full_key] = result
    checkpoint_cache("full-text")
    return result


def local_translate_part(part, strict=False):
    return localize_or_translate(str(part or ""), strict=strict)


def _translate_short_group(group):
    model_group = []
    for text, strict in group:
        fixed = deterministic_time_label(text)
        if fixed is not None:
            base.CACHE[cache_key(text)] = fixed
            checkpoint_cache("short-deterministic-time-label")
        else:
            model_group.append((text, strict))

    if not model_group:
        return

    source_texts = [text for text, _strict in model_group]
    outputs = local_zh_ja.translate_many(source_texts, batch_size=OWNER_BATCH_SIZE)
    if len(outputs) != len(model_group):
        raise RuntimeError("Local OPUS-MT returned wrong owner batch size")
    for index, ((text, strict), value) in enumerate(zip(model_group, outputs), 1):
        value = _validated_translation(text, value, strict=strict)
        base.CACHE[cache_key(text)] = value
        # Persist every successful item before attempting the next difficult item.
        checkpoint_cache(f"short-item-{index}-of-{len(model_group)}")


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
        fixed = deterministic_time_label(text)
        if fixed is not None:
            base.CACHE[cache_key(text)] = fixed
            local_count += 1
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
    """Use local OPUS-MT for bulk translation with validated per-field repairs."""
    fast.bounded_gtx = local_translate_part
    fast.bounded_mymemory = local_translate_part
    fast.bounded_translate_part = local_translate_part
    fast.prewarm_translations = local_prewarm_translations

    def installer():
        # Legacy production hooks use local bulk translation. The captured
        # originals above remain available solely inside _remote_quality_fallback.
        safe.google_gtx_translate = local_translate_part
        safe.google_translate = local_translate_part
        safe.mymemory_translate = local_translate_part
        safe.safe_translate_part = local_translate_part
        base.translate_part = lambda part: local_translate_part(part, strict=False)

    fast.install_bounded_translator = installer
    installer()
    print(
        "LOCAL_MT_RUNTIME_INSTALLED remote_translation_calls=quality-fallback-only "
        "model=Helsinki-NLP/opus-mt-tc-big-zh-ja"
    )
