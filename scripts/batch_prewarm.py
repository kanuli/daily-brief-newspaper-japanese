#!/usr/bin/env python3
"""Batch-prewarm Japanese translations for every Cantonese publication layer.

Why this exists:
- the Cantonese repository is the only news source;
- translating one field per HTTP request can exhaust free translator quotas;
- Daily/Live and rolling/topic layers must share one cache before conversion.

This script fetches all current Cantonese JSON layers, collects the exact
user-facing strings used by the Japanese converter, translates many short text
segments in each request, validates every reconstructed Japanese value with the
existing quality gate, and writes data/translation-cache.json. The existing
safe/incremental converters then consume that cache without changing story
selection, IDs, section membership, furigana, or audio paths.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from dataclasses import dataclass
from typing import Iterable

import requests

import fast_safe_sync as fast
import safe_sync as safe
import sync_and_translate as base

SOURCE_BASE = base.SOURCE_BASE
CACHE_PATH = base.CACHE_PATH
BATCH_SOURCE_CHAR_LIMIT = 620
PART_CHAR_LIMIT = 420
REQUEST_TIMEOUT = 15
REQUEST_PAUSE = 0.8
MAX_GTX_ATTEMPTS = 4
MAX_DEEP_ATTEMPTS = 2
MARKER_RE = re.compile(r"<<<\s*DBJ(\d{5})\s*>>>", re.I)
HAN_RE = re.compile(r"[\u3400-\u9fff]")
HIRA_RE = re.compile(r"[\u3040-\u309f]")
ORIGINAL_LIKELY_CHINESE = base.likely_chinese_source


@dataclass(frozen=True)
class Segment:
    marker: int
    owner: int
    part_index: int
    text: str


def needs_cantonese_translation(value: str) -> bool:
    """Recognize Cantonese prose even when Japanese names/kana are embedded."""
    text = str(value or "")
    if not text.strip():
        return False
    if safe.CHINESE_PROSE_RE.search(text):
        return True
    if ORIGINAL_LIKELY_CHINESE(text):
        return True
    han = len(HAN_RE.findall(text))
    hira = len(HIRA_RE.findall(text))
    return han >= 10 and hira < max(4, int(han * 0.12))


def cache_key(text: str) -> str:
    return hashlib.sha256(f"{base.CACHE_VERSION}|{text}".encode("utf-8")).hexdigest()


def fetch_json(name: str, optional: bool = False):
    response = requests.get(
        f"{SOURCE_BASE}/{name}",
        timeout=30,
        headers={"User-Agent": "daily-brief-newspaper-japanese-batch-prewarm"},
    )
    if optional and response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def source_files() -> list[tuple[str, object]]:
    latest = fetch_json("latest.json")
    date = str((latest or {}).get("date") or "")
    names = [
        ("latest.json", latest, False),
        ("live.json", None, False),
        ("archive.json", None, False),
        ("desk-latest.json", None, False),
        ("stocks-latest.json", None, False),
    ]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        names.append((f"topic-more/{date}.json", None, True))

    found = []
    for name, already, optional in names:
        payload = already if already is not None else fetch_json(name, optional=optional)
        if payload is not None:
            found.append((name, payload))
    return found


def collect_candidates(files: Iterable[tuple[str, object]]):
    out: dict[str, bool] = {}
    per_file = {}
    for name, payload in files:
        current = fast.collect_translatable(payload)
        per_file[name] = len(current)
        for text, strict in current.items():
            out[text] = out.get(text, False) or bool(strict)
    return out, per_file


def valid_cached(text: str, strict: bool) -> bool:
    value = base.CACHE.get(cache_key(text))
    return value is not None and safe.target_quality_ok(text, value, strict=strict)


def build_parts(text: str) -> list[str]:
    parts = base.chunks(text, limit=PART_CHAR_LIMIT)
    return parts if parts else [text]


def make_segments(texts: list[tuple[str, bool]]):
    owner_parts: dict[int, list[str]] = {}
    segments: list[Segment] = []
    marker = 1
    for owner, (text, _strict) in enumerate(texts):
        parts = build_parts(text)
        owner_parts[owner] = parts
        for part_index, part in enumerate(parts):
            if not part.strip():
                continue
            segments.append(Segment(marker, owner, part_index, part))
            marker += 1
    return segments, owner_parts


def group_segments(segments: list[Segment]) -> list[list[Segment]]:
    batches: list[list[Segment]] = []
    current: list[Segment] = []
    size = 0
    for segment in segments:
        overhead = 20
        segment_size = len(segment.text) + overhead
        if current and size + segment_size > BATCH_SOURCE_CHAR_LIMIT:
            batches.append(current)
            current = []
            size = 0
        current.append(segment)
        size += segment_size
    if current:
        batches.append(current)
    return batches


def batch_payload(batch: list[Segment]) -> str:
    return "\n".join(f"<<<DBJ{item.marker:05d}>>>\n{item.text}" for item in batch)


def extract_gtx(response: requests.Response) -> str:
    payload = response.json()
    segments = payload[0] if isinstance(payload, list) and payload else []
    return "".join(
        str(segment[0])
        for segment in segments
        if isinstance(segment, list) and segment and segment[0]
    )


def gtx_request(payload: str) -> str:
    last = None
    for attempt in range(1, MAX_GTX_ATTEMPTS + 1):
        try:
            response = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "zh-TW", "tl": "ja", "dt": "t", "q": payload},
                headers={"User-Agent": "Mozilla/5.0 daily-brief-newspaper-japanese-batch"},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code in (429, 503):
                raise RuntimeError(f"GTX HTTP {response.status_code}")
            response.raise_for_status()
            return extract_gtx(response)
        except Exception as exc:
            last = exc
            delay = min(18.0, 2.0 * (2 ** (attempt - 1)))
            print(f"BATCH_GTX_RETRY attempt={attempt}/{MAX_GTX_ATTEMPTS} delay={delay:.1f}s error={exc}")
            time.sleep(delay)
    raise RuntimeError(str(last or "GTX batch failed"))


def deep_google_request(payload: str) -> str:
    last = None
    for source in ("zh-TW", "auto"):
        for attempt in range(1, MAX_DEEP_ATTEMPTS + 1):
            try:
                value = base.GoogleTranslator(source=source, target="ja").translate(payload)
                if not isinstance(value, str) or not value.strip():
                    raise RuntimeError("empty deep-translator batch")
                return value
            except Exception as exc:
                last = exc
                time.sleep(1.5 * attempt)
    raise RuntimeError(str(last or "deep Google batch failed"))


def mymemory_request(payload: str) -> str:
    response = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": payload, "langpair": "zh-TW|ja"},
        headers={"User-Agent": "daily-brief-newspaper-japanese-batch"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    value = html.unescape(str((data.get("responseData") or {}).get("translatedText") or ""))
    if not value.strip():
        raise RuntimeError("empty MyMemory batch")
    return value


def parse_batch(translated: str, batch: list[Segment]) -> dict[int, str]:
    pieces = MARKER_RE.split(str(translated or ""))
    found: dict[int, str] = {}
    for index in range(1, len(pieces), 2):
        try:
            marker = int(pieces[index])
        except Exception:
            continue
        found[marker] = pieces[index + 1].strip() if index + 1 < len(pieces) else ""
    expected = {item.marker for item in batch}
    if set(found) != expected or any(not found.get(marker) for marker in expected):
        missing = sorted(expected - set(found))
        raise RuntimeError(f"batch marker parse mismatch missing={missing[:8]} expected={len(expected)} got={len(found)}")
    return found


def translate_batch_once(batch: list[Segment]) -> dict[int, str]:
    payload = batch_payload(batch)
    errors = []
    for label, func in (("gtx", gtx_request), ("deep-google", deep_google_request), ("mymemory", mymemory_request)):
        try:
            translated = func(payload)
            result = parse_batch(translated, batch)
            print(f"BATCH_TRANSLATOR_OK backend={label} items={len(batch)} chars={len(payload)}")
            return result
        except Exception as exc:
            errors.append(f"{label}={type(exc).__name__}:{exc}")
            print(f"BATCH_TRANSLATOR_FAIL backend={label} items={len(batch)} error={exc}")
    raise RuntimeError("; ".join(errors))


def translate_batch(batch: list[Segment]) -> dict[int, str]:
    try:
        result = translate_batch_once(batch)
        time.sleep(REQUEST_PAUSE)
        return result
    except Exception:
        if len(batch) <= 1:
            item = batch[0]
            value = fast.bounded_translate_part(item.text, strict=False)
            return {item.marker: value}
        midpoint = len(batch) // 2
        print(f"BATCH_SPLIT items={len(batch)} -> {midpoint}+{len(batch)-midpoint}")
        left = translate_batch(batch[:midpoint])
        right = translate_batch(batch[midpoint:])
        left.update(right)
        return left


def prewarm_all() -> None:
    base.likely_chinese_source = needs_cantonese_translation
    fast.install_bounded_translator()
    safe.prune_cache()

    files = source_files()
    candidates, per_file = collect_candidates(files)
    pending_chinese: list[tuple[str, bool]] = []
    local_count = 0
    cached_count = 0

    for text, strict in candidates.items():
        if valid_cached(text, strict):
            cached_count += 1
            continue
        if not needs_cantonese_translation(text):
            value = fast.localize_non_chinese(text)
            if not safe.target_quality_ok(text, value, strict=strict):
                raise RuntimeError(f"local Japanese normalization failed: {text[:100]!r}")
            base.CACHE[cache_key(text)] = value
            local_count += 1
            continue
        pending_chinese.append((text, strict))

    segments, owner_parts = make_segments(pending_chinese)
    batches = group_segments(segments)
    print(
        "BATCH_PREWARM_PLAN",
        f"files={len(files)} unique={len(candidates)} cached={cached_count}",
        f"local={local_count} chinese={len(pending_chinese)} segments={len(segments)} batches={len(batches)}",
        f"per_file={per_file}",
    )

    translated_segments: dict[int, str] = {}
    for number, batch in enumerate(batches, 1):
        print(f"BATCH_PREWARM_PROGRESS {number}/{len(batches)} items={len(batch)}")
        translated_segments.update(translate_batch(batch))

    owner_marker_by_part: dict[tuple[int, int], int] = {
        (item.owner, item.part_index): item.marker for item in segments
    }
    for owner, (source_text, strict) in enumerate(pending_chinese):
        rebuilt = []
        for part_index, part in enumerate(owner_parts[owner]):
            if not part.strip():
                rebuilt.append(part)
                continue
            marker = owner_marker_by_part[(owner, part_index)]
            rebuilt.append(translated_segments[marker])
        value = "".join(rebuilt)
        if not safe.target_quality_ok(source_text, value, strict=strict):
            raise RuntimeError(f"batch Japanese quality gate failed: {source_text[:120]!r}")
        base.CACHE[cache_key(source_text)] = value

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(base.CACHE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "BATCH_PREWARM_OK",
        f"files={','.join(name for name, _ in files)}",
        f"cache_entries={len(base.CACHE)} newly_translated={len(pending_chinese)}",
    )


if __name__ == "__main__":
    prewarm_all()
