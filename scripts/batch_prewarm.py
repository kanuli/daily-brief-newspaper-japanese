#!/usr/bin/env python3
"""Resumable Cantonese -> Japanese translation cache prewarm.

The Cantonese repository remains the only news source. This stage exists only
to translate its already-edited publication data. It deliberately avoids a
retry tree: a rate-limited backend is bypassed for the rest of the run, batch
fallbacks translate small pieces directly, and validated progress is written to
translation-cache.json after every batch so a later run can resume.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

import fast_safe_sync as fast
import safe_sync as safe
import sync_and_translate as base

SOURCE_BASE = base.SOURCE_BASE
CACHE_PATH = base.CACHE_PATH
BATCH_SOURCE_CHAR_LIMIT = 520
PART_CHAR_LIMIT = 360
REQUEST_TIMEOUT = 10
REQUEST_PAUSE = 0.35
MARKER_RE = re.compile(r"<<<\s*DBJ(\d{5})\s*>>>", re.I)
HAN_RE = re.compile(r"[\u3400-\u9fff]")
HIRA_RE = re.compile(r"[\u3040-\u309f]")
ORIGINAL_LIKELY_CHINESE = base.likely_chinese_source
GTX_CIRCUIT_OPEN = False


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


def checkpoint_cache(label: str) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(base.CACHE, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"TRANSLATION_CACHE_CHECKPOINT {label} entries={len(base.CACHE)}")


def fetch_json(name: str, optional: bool = False):
    response = requests.get(
        f"{SOURCE_BASE}/{name}",
        timeout=30,
        headers={"User-Agent": "daily-brief-newspaper-japanese-resumable"},
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


def indexed_items(value, out=None):
    """Index dict objects carrying stable story ids anywhere in a JSON layer."""
    if out is None:
        out = {}
    if isinstance(value, dict):
        item_id = value.get("id")
        if isinstance(item_id, str) and item_id:
            out[item_id] = value
        for child in value.values():
            indexed_items(child, out)
    elif isinstance(value, list):
        for child in value:
            indexed_items(child, out)
    return out


def seed_cache_from_existing(files: list[tuple[str, object]]) -> int:
    """Reuse already-good Japanese fields for unchanged story ids.

    The cache may lag behind the rendered Japanese JSON because older runs only
    wrote it at the end. Recovering these translations first drastically cuts
    remote translator work, especially for the rolling desk.
    """
    seeded = 0
    for name, source in files:
        local_path = Path("data") / name
        if not local_path.exists():
            continue
        try:
            existing = json.loads(local_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        src_index = indexed_items(source)
        dst_index = indexed_items(existing)
        for item_id, src_item in src_index.items():
            dst_item = dst_index.get(item_id)
            if not isinstance(dst_item, dict):
                continue
            for key, source_text in src_item.items():
                if key not in base.TRANSLATE_KEYS or not isinstance(source_text, str) or not source_text.strip():
                    continue
                target = dst_item.get(key)
                strict = key in safe.STRICT_PROSE_KEYS
                if not isinstance(target, str) or not safe.target_quality_ok(source_text, target, strict=strict):
                    continue
                ckey = cache_key(source_text)
                if base.CACHE.get(ckey) != target:
                    base.CACHE[ckey] = target
                    seeded += 1
    if seeded:
        checkpoint_cache(f"seeded-existing-{seeded}")
    print(f"TRANSLATION_CACHE_SEEDED_FROM_EXISTING {seeded}")
    return seeded


def build_parts(text: str) -> list[str]:
    parts = base.chunks(text, limit=PART_CHAR_LIMIT)
    return parts if parts else [text]


def make_segments(texts: list[tuple[str, bool]]):
    owner_parts: dict[int, list[str]] = {}
    part_values: dict[tuple[int, int], str] = {}
    segments: list[Segment] = []
    marker = 1
    for owner, (text, _strict) in enumerate(texts):
        parts = build_parts(text)
        owner_parts[owner] = parts
        for part_index, part in enumerate(parts):
            if not part.strip():
                continue
            cached_part = base.CACHE.get(cache_key(part))
            if cached_part is not None and safe.target_quality_ok(part, cached_part, strict=False):
                part_values[(owner, part_index)] = cached_part
                continue
            segments.append(Segment(marker, owner, part_index, part))
            marker += 1
    return segments, owner_parts, part_values


def group_segments(segments: list[Segment]) -> list[list[Segment]]:
    batches: list[list[Segment]] = []
    current: list[Segment] = []
    size = 0
    for segment in segments:
        segment_size = len(segment.text) + 20
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
        raise RuntimeError(f"batch marker parse mismatch expected={len(expected)} got={len(found)}")
    return found


def extract_gtx(response: requests.Response) -> str:
    payload = response.json()
    segments = payload[0] if isinstance(payload, list) and payload else []
    return "".join(
        str(segment[0])
        for segment in segments
        if isinstance(segment, list) and segment and segment[0]
    )


def gtx_batch_once(batch: list[Segment]) -> dict[int, str]:
    """Try the efficient batch endpoint once. 429 opens a run-wide circuit."""
    global GTX_CIRCUIT_OPEN
    if GTX_CIRCUIT_OPEN:
        raise RuntimeError("GTX circuit already open")
    payload = batch_payload(batch)
    response = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "zh-TW", "tl": "ja", "dt": "t", "q": payload},
        headers={"User-Agent": "Mozilla/5.0 daily-brief-newspaper-japanese-resumable"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code in (429, 503):
        GTX_CIRCUIT_OPEN = True
        print(f"GTX_CIRCUIT_OPEN HTTP {response.status_code}; no more GTX retries this run")
        raise RuntimeError(f"GTX HTTP {response.status_code}")
    response.raise_for_status()
    result = parse_batch(extract_gtx(response), batch)
    for item in batch:
        value = result[item.marker]
        if not safe.target_quality_ok(item.text, value, strict=False):
            raise RuntimeError(f"GTX batch quality failure marker={item.marker}")
    return result


def deep_google_single(text: str) -> str:
    errors = []
    for source in ("zh-TW", "auto"):
        try:
            value = base.GoogleTranslator(source=source, target="ja").translate(text)
            if not isinstance(value, str) or not safe.target_quality_ok(text, value, strict=False):
                raise RuntimeError("invalid Japanese result")
            return value
        except Exception as exc:
            errors.append(f"{source}={type(exc).__name__}:{exc}")
    raise RuntimeError("; ".join(errors))


def mymemory_single(text: str) -> str:
    response = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text, "langpair": "zh-TW|ja"},
        headers={"User-Agent": "daily-brief-newspaper-japanese-resumable"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    value = html.unescape(str((data.get("responseData") or {}).get("translatedText") or ""))
    if not safe.target_quality_ok(text, value, strict=False):
        raise RuntimeError("invalid MyMemory Japanese result")
    return value


def translate_single(item: Segment) -> str:
    """Marker-free fallback: each piece is translated independently exactly once."""
    errors = []
    try:
        return deep_google_single(item.text)
    except Exception as exc:
        errors.append(f"deep-google={exc}")
    try:
        return mymemory_single(item.text)
    except Exception as exc:
        errors.append(f"mymemory={exc}")
    raise RuntimeError(
        f"all direct fallbacks failed marker={item.marker}: " + "; ".join(errors)
    )


def translate_batch(batch: list[Segment]) -> dict[int, str]:
    if not GTX_CIRCUIT_OPEN:
        try:
            result = gtx_batch_once(batch)
            print(f"BATCH_TRANSLATOR_OK backend=gtx items={len(batch)}")
            time.sleep(REQUEST_PAUSE)
            return result
        except Exception as exc:
            print(f"BATCH_GTX_BYPASS items={len(batch)} error={exc}")

    # Do not recurse and do not send marker-wrapped payloads to fallbacks.
    # Translating each small segment directly is slower than a healthy GTX
    # batch, but deterministic and cannot explode into an exponential retry tree.
    out = {}
    for item in batch:
        out[item.marker] = translate_single(item)
        time.sleep(REQUEST_PAUSE)
    print(f"BATCH_TRANSLATOR_OK backend=direct-fallback items={len(batch)}")
    return out


def finalize_ready_owners(
    pending_chinese: list[tuple[str, bool]],
    owner_parts: dict[int, list[str]],
    part_values: dict[tuple[int, int], str],
    finalized: set[int],
) -> int:
    completed = 0
    for owner, (source_text, strict) in enumerate(pending_chinese):
        if owner in finalized:
            continue
        rebuilt = []
        ready = True
        for part_index, part in enumerate(owner_parts[owner]):
            if not part.strip():
                rebuilt.append(part)
                continue
            value = part_values.get((owner, part_index))
            if value is None:
                ready = False
                break
            rebuilt.append(value)
        if not ready:
            continue
        value = "".join(rebuilt)
        if not safe.target_quality_ok(source_text, value, strict=strict):
            raise RuntimeError(f"Japanese quality gate failed: {source_text[:120]!r}")
        base.CACHE[cache_key(source_text)] = value
        finalized.add(owner)
        completed += 1
    return completed


def prewarm_all() -> None:
    base.likely_chinese_source = needs_cantonese_translation
    safe.prune_cache()

    files = source_files()
    seed_cache_from_existing(files)
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

    checkpoint_cache("after-seed-and-local")
    segments, owner_parts, part_values = make_segments(pending_chinese)
    batches = group_segments(segments)
    finalized: set[int] = set()
    initial_completed = finalize_ready_owners(
        pending_chinese, owner_parts, part_values, finalized
    )
    if initial_completed:
        checkpoint_cache(f"part-cache-reuse-{initial_completed}")

    print(
        "BATCH_PREWARM_PLAN",
        f"files={len(files)} unique={len(candidates)} cached={cached_count}",
        f"local={local_count} chinese={len(pending_chinese)} segments={len(segments)} batches={len(batches)}",
        f"per_file={per_file}",
    )

    for number, batch in enumerate(batches, 1):
        print(f"BATCH_PREWARM_PROGRESS {number}/{len(batches)} items={len(batch)}")
        translated = translate_batch(batch)
        for item in batch:
            value = translated[item.marker]
            part_values[(item.owner, item.part_index)] = value
            # Part-level cache allows a multi-part field to resume too.
            base.CACHE[cache_key(item.text)] = value
        newly_finalized = finalize_ready_owners(
            pending_chinese, owner_parts, part_values, finalized
        )
        checkpoint_cache(
            f"batch-{number}-of-{len(batches)}-owners+{newly_finalized}"
        )

    if len(finalized) != len(pending_chinese):
        raise RuntimeError(
            f"translation prewarm incomplete finalized={len(finalized)} expected={len(pending_chinese)}"
        )

    print(
        "BATCH_PREWARM_OK",
        f"files={','.join(name for name, _ in files)}",
        f"cache_entries={len(base.CACHE)} newly_translated={len(pending_chinese)}",
    )


if __name__ == "__main__":
    prewarm_all()
