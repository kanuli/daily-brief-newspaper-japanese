#!/usr/bin/env python3
"""Install the local OPUS-MT translator into the existing Japanese pipeline."""
from __future__ import annotations

import hashlib

import fast_safe_sync as fast
import local_zh_ja
import safe_sync as safe
import sync_and_translate as base


def cache_key(text: str) -> str:
    return hashlib.sha256(f"{base.CACHE_VERSION}|{text}".encode("utf-8")).hexdigest()


def local_translate_part(part, strict=False):
    text = str(part or "")
    if not base.likely_chinese_source(text):
        return fast.localize_non_chinese(text)
    value = local_zh_ja.translate_one(text)
    if not safe.target_quality_ok(text, value, strict=strict):
        raise RuntimeError(f"Local OPUS-MT quality gate failed: {text[:100]!r}")
    return value


def local_prewarm_translations(source, label):
    candidates = fast.collect_translatable(source)
    pending = []
    for text, strict in candidates.items():
        cached = base.CACHE.get(cache_key(text))
        if cached is not None and safe.target_quality_ok(text, cached, strict=strict):
            continue
        if not base.likely_chinese_source(text):
            value = fast.localize_non_chinese(text)
            if not safe.target_quality_ok(text, value, strict=strict):
                raise RuntimeError(f"Local normalization failed: {text[:100]!r}")
            base.CACHE[cache_key(text)] = value
            continue
        pending.append((text, strict))

    if not pending:
        print(f"LOCAL_MT_PREWARM {label}: pending=0")
        return

    print(f"LOCAL_MT_PREWARM {label}: pending={len(pending)}")
    for start in range(0, len(pending), 4):
        group = pending[start : start + 4]
        source_texts = [text for text, _strict in group]
        translated = local_zh_ja.translate_many(source_texts, batch_size=4)
        for (text, strict), value in zip(group, translated):
            if not safe.target_quality_ok(text, value, strict=strict):
                raise RuntimeError(f"Local OPUS-MT quality gate failed: {text[:100]!r}")
            base.CACHE[cache_key(text)] = value
    print(f"LOCAL_MT_PREWARM_OK {label}: translated={len(pending)}")


def install():
    """Replace every production translation hook with local OPUS-MT."""
    fast.bounded_gtx = local_translate_part
    fast.bounded_mymemory = local_translate_part
    fast.bounded_translate_part = local_translate_part
    fast.prewarm_translations = local_prewarm_translations

    def installer():
        safe.google_gtx_translate = local_translate_part
        safe.google_translate = local_translate_part
        safe.mymemory_translate = local_translate_part
        safe.safe_translate_part = local_translate_part
        base.translate_part = lambda part: local_translate_part(part, strict=False)

    fast.install_bounded_translator = installer
    installer()
    print("LOCAL_MT_RUNTIME_INSTALLED google_calls=disabled model=Helsinki-NLP/opus-mt-tc-big-zh-ja")
