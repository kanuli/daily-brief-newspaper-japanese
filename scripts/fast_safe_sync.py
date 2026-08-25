#!/usr/bin/env python3
"""Fast, incremental downstream translation of the Cantonese newspaper.

The Cantonese repository is the only news source. This wrapper preserves the
existing safe_sync quality/furigana/audio rules while adding two guarantees for
the hourly Japanese edition:
1. free translation network calls have short bounded timeouts/retries;
2. unchanged Cantonese stories reuse their existing Japanese translation, so a
   changing Live timestamp does not cause the whole edition to be translated.
"""
import hashlib
import html
import json

import requests

import safe_sync as safe
import sync_and_translate as base

GTX_TIMEOUT = 6
MYMEMORY_TIMEOUT = 6
GTX_SOURCES_CHINESE = ("zh-TW", "auto")
GTX_SOURCES_OTHER = ("auto",)
MYMEMORY_MAX_CHARS = 900
MYMEMORY_PIECE_LIMIT = 450


def bounded_gtx(part, strict=False):
    """At most one short HTTP attempt per source language."""
    sources = GTX_SOURCES_CHINESE if base.likely_chinese_source(part) else GTX_SOURCES_OTHER
    errors = []
    for source in sources:
        try:
            response = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": source, "tl": "ja", "dt": "t", "q": part},
                headers={"User-Agent": "Mozilla/5.0 daily-brief-newspaper-japanese-fast"},
                timeout=GTX_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            segments = payload[0] if isinstance(payload, list) and payload else []
            value = "".join(
                str(segment[0])
                for segment in segments
                if isinstance(segment, list) and segment and segment[0]
            )
            if not safe.target_quality_ok(part, value, strict=strict):
                raise RuntimeError(f"GTX {source} returned invalid/non-Japanese payload")
            return value
        except Exception as exc:
            errors.append(f"{source}={type(exc).__name__}:{exc}")
    raise RuntimeError("; ".join(errors) or "bounded GTX failed")


def bounded_mymemory(part, strict=False):
    """Bounded HTTP fallback for short Chinese fields only."""
    if not base.likely_chinese_source(part):
        raise RuntimeError("MyMemory fallback only applies to Chinese source text")
    if len(part) > MYMEMORY_MAX_CHARS:
        raise RuntimeError(f"MyMemory fallback skipped for long field ({len(part)} chars)")

    pieces = base.chunks(part, limit=MYMEMORY_PIECE_LIMIT)
    if len(pieces) > 2:
        raise RuntimeError("MyMemory fallback limited to two short requests")

    translated = []
    for piece in pieces:
        if not piece.strip():
            translated.append(piece)
            continue
        response = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": piece, "langpair": "zh-TW|ja"},
            headers={"User-Agent": "daily-brief-newspaper-japanese-fast"},
            timeout=MYMEMORY_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        value = html.unescape(str((payload.get("responseData") or {}).get("translatedText") or ""))
        if not safe.target_quality_ok(piece, value, strict=strict):
            raise RuntimeError("MyMemory returned invalid/non-Japanese payload")
        translated.append(value)

    value = "".join(translated)
    if not safe.target_quality_ok(part, value, strict=strict):
        raise RuntimeError("MyMemory combined translation failed quality checks")
    return value


def bounded_translate_part(part, strict=False):
    errors = []
    try:
        return bounded_gtx(part, strict=strict)
    except Exception as exc:
        errors.append(f"gtx={exc}")
    if base.likely_chinese_source(part):
        try:
            return bounded_mymemory(part, strict=strict)
        except Exception as exc:
            errors.append(f"mymemory={exc}")
    raise RuntimeError("Bounded Japanese translation failed; " + "; ".join(errors))


def cache_key(text):
    return hashlib.sha256(f"{base.CACHE_VERSION}|{text}".encode("utf-8")).hexdigest()


def legacy_item_reusable(source_item, old_item):
    """Bootstrap reuse for items created before sourceItemFingerprint existed.

    Reuse is allowed only when every translatable source string has a valid
    cached Japanese value identical to the old item and stable identity fields
    have not changed. This prevents a stale old story from masking source edits.
    """
    if not isinstance(source_item, dict) or not isinstance(old_item, dict):
        return False
    if source_item.get("id") != old_item.get("id"):
        return False
    for key in ("id", "desk", "slug", "sourceName", "sourceUrl", "url", "status", "date"):
        if key in source_item and source_item.get(key) != old_item.get(key):
            return False
    for key, value in source_item.items():
        if key not in base.TRANSLATE_KEYS or not isinstance(value, str) or not value.strip():
            continue
        cached = base.CACHE.get(cache_key(value))
        if cached is None or old_item.get(key) != cached:
            return False
        if not safe.target_quality_ok(value, cached, strict=key in safe.STRICT_PROSE_KEYS):
            return False
    return True


def incremental_convert(name, source, existing):
    list_key = "articles" if name == "latest.json" else "items"
    source_items = source.get(list_key) if isinstance(source, dict) else None
    if name not in ("latest.json", "live.json") or not isinstance(source_items, list):
        return base.convert(source)

    shell = dict(source)
    shell.pop(list_key, None)
    translated = base.convert(shell)
    old_items = {
        item.get("id"): item
        for item in (existing or {}).get(list_key, [])
        if isinstance(item, dict) and item.get("id")
    }

    output = []
    reused = 0
    changed = 0
    for source_item in source_items:
        if not isinstance(source_item, dict):
            output.append(base.convert(source_item))
            changed += 1
            continue
        item_id = source_item.get("id")
        item_fingerprint = base.source_fingerprint(source_item)
        old = old_items.get(item_id)
        can_reuse = bool(
            old
            and (
                old.get("sourceItemFingerprint") == item_fingerprint
                or (not old.get("sourceItemFingerprint") and legacy_item_reusable(source_item, old))
            )
        )
        if can_reuse:
            item = dict(old)
            reused += 1
        else:
            item = base.convert(source_item)
            changed += 1
        if isinstance(item, dict):
            item["sourceItemFingerprint"] = item_fingerprint
        output.append(item)

    translated[list_key] = output
    print(f"INCREMENTAL_TRANSLATION {name}: reused={reused} changed={changed} total={len(output)}")
    return translated


def incremental_main():
    base.OUT.mkdir(exist_ok=True)
    done = []
    skipped = []
    for name in base.FILES:
        src = base.fetch(name)
        if src is None:
            continue
        fingerprint = base.source_fingerprint(src)
        existing = base.load_existing(name)
        if (
            existing
            and existing.get("sourceFingerprint") == fingerprint
            and existing.get("translationSchemaVersion") == base.TRANSLATION_SCHEMA
            and base.existing_features_ok(name, existing)
        ):
            (base.OUT / name).write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            skipped.append(name)
            continue

        translated = incremental_convert(name, src, existing)
        if name == "latest.json":
            translated = base.add_furigana(base.attach_daily_audio(translated), "articles")
        if name == "live.json":
            translated = base.add_furigana(base.attach_live_audio(translated), "items")
        if name == "archive.json":
            translated = base.add_archive_furigana(translated)
        if isinstance(translated, dict):
            translated["language"] = "ja"
            translated["translationSource"] = "kanuli/daily-brief-newspaper"
            translated["sourceFile"] = name
            translated["sourceFingerprint"] = fingerprint
            translated["translationSchemaVersion"] = base.TRANSLATION_SCHEMA
        (base.OUT / name).write_text(json.dumps(translated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        done.append(name)

    base.CACHE_PATH.write_text(json.dumps(base.CACHE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Japanese data updated:", ", ".join(done) if done else "none")
    print("Fingerprint fast-path:", ", ".join(skipped) if skipped else "none")


def main():
    safe.google_gtx_translate = bounded_gtx
    safe.mymemory_translate = bounded_mymemory
    safe.safe_translate_part = bounded_translate_part
    # safe.main installs safe_convert/quality gates, then calls base.main. Point
    # base.main at the incremental implementation before invoking safe.main.
    base.main = incremental_main
    safe.main()


if __name__ == "__main__":
    main()
