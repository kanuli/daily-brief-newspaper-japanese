#!/usr/bin/env python3
"""Run the existing hardened Japanese sync with bounded network translation latency.

The Cantonese repository remains the only news source. This wrapper only changes
how long free translation backends are allowed to block an hourly Japanese run.
It preserves safe_sync's quality checks, deterministic Live labels, furigana,
audio paths, fingerprints, and publication semantics.
"""
import html

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
    """Bounded HTTP fallback for short Chinese fields only.

    Long bodies are intentionally not split into many fallback requests. If GTX
    cannot translate a long body, fail the item quickly and let the workflow
    report the problem instead of freezing the whole edition for 30 minutes.
    """
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


def main():
    # safe_sync resolves safe_translate_part from its module globals at runtime,
    # so replacing it here also affects safe_translate_text and safe.main.
    safe.google_gtx_translate = bounded_gtx
    safe.mymemory_translate = bounded_mymemory
    safe.safe_translate_part = bounded_translate_part
    safe.main()


if __name__ == "__main__":
    main()
