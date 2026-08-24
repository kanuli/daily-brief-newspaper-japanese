#!/usr/bin/env python3
"""Hardened wrapper around sync_and_translate.

Rejects translator error pages and partially untranslated Traditional Chinese,
uses multiple free translation backends as fallbacks, normalizes Live schedule
metadata deterministically, and only hands clean Japanese data to the existing
furigana/audio pipeline.
"""
import hashlib
import re
import time

import requests
from deep_translator import MyMemoryTranslator
import sync_and_translate as base
import validate_content_integrity as integrity

ERROR_RE = re.compile(
    r"(?:error\s*(?:4\d\d|5\d\d)|server error|that[’']s an error|please try again later|"
    r"bad gateway|service unavailable|too many requests|internal server error|<!doctype|<html)",
    re.I,
)
HIRA_RE = re.compile(r"[\u3040-\u309f]")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
CHINESE_PROSE_RE = integrity.CHINESE_PROSE_RE
STRICT_PROSE_KEYS = {"dek", "summary", "body", "context", "why", "watchNext", "description", "note"}
_ORIGINAL_EXISTING_FEATURES_OK = base.existing_features_ok


def bad_error_text(value):
    return bool(ERROR_RE.search(str(value or "")))


def target_quality_ok(source_text, value, strict=False):
    source_text = str(source_text or "")
    value = str(value or "")
    if not value.strip() or bad_error_text(value):
        return False
    if CHINESE_PROSE_RE.search(value):
        return False
    if not base.likely_chinese_source(source_text):
        return True
    if value.strip() == source_text.strip() and len(source_text.strip()) > 18:
        return False
    if strict and len(source_text.strip()) >= 28:
        han = len(HAN_RE.findall(value))
        hira = len(HIRA_RE.findall(value))
        if han >= 8 and hira < max(2, int(han * 0.06)):
            return False
    return True


def google_gtx_translate(part, strict=False):
    """Use Google's lightweight translate endpoint before HTML-scraping backends.

    The endpoint returns JSON rather than an HTML page, so upstream 4xx/5xx pages
    cannot be mistaken for translated article text. No API key is required.
    """
    sources = ("zh-TW", "auto", "zh-CN") if base.likely_chinese_source(part) else ("auto",)
    last_error = None
    for source in sources:
        for attempt in range(3):
            try:
                response = requests.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params={"client": "gtx", "sl": source, "tl": "ja", "dt": "t", "q": part},
                    headers={"User-Agent": "Mozilla/5.0 daily-brief-newspaper-japanese"},
                    timeout=25,
                )
                response.raise_for_status()
                payload = response.json()
                segments = payload[0] if isinstance(payload, list) and payload else []
                value = "".join(
                    str(segment[0]) for segment in segments
                    if isinstance(segment, list) and segment and segment[0]
                )
                if not target_quality_ok(part, value, strict=strict):
                    raise RuntimeError(f"GTX {source} returned invalid/non-Japanese payload")
                return value
            except Exception as exc:
                last_error = exc
                time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(str(last_error or "Google GTX translation failed"))


def google_translate(part, strict=False):
    sources = ("zh-TW", "auto", "zh-CN") if base.likely_chinese_source(part) else ("auto",)
    last_error = None
    for source in sources:
        for attempt in range(2):
            try:
                value = base.GoogleTranslator(source=source, target="ja").translate(part)
                if not target_quality_ok(part, value, strict=strict):
                    raise RuntimeError(f"{source} returned invalid/non-Japanese translator payload")
                return value
            except Exception as exc:
                last_error = exc
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(str(last_error or "Google translation failed"))


def mymemory_translate(part, strict=False):
    if not base.likely_chinese_source(part):
        raise RuntimeError("MyMemory fallback is only enabled for Chinese source text")
    pieces = base.chunks(part, limit=450)
    translated = []
    for piece in pieces:
        if not piece.strip():
            translated.append(piece)
            continue
        value = MyMemoryTranslator(source="chinese traditional", target="japanese").translate(piece)
        if not target_quality_ok(piece, value, strict=strict):
            raise RuntimeError("MyMemory returned invalid/non-Japanese translator payload")
        translated.append(value)
        time.sleep(0.15)
    value = "".join(translated)
    if not target_quality_ok(part, value, strict=strict):
        raise RuntimeError("MyMemory combined translation failed quality checks")
    return value


def safe_translate_part(part, strict=False):
    errors = []
    try:
        return google_gtx_translate(part, strict=strict)
    except Exception as exc:
        errors.append(f"gtx={exc}")
    try:
        return google_translate(part, strict=strict)
    except Exception as exc:
        errors.append(f"deep_google={exc}")
    if base.likely_chinese_source(part):
        try:
            return mymemory_translate(part, strict=strict)
        except Exception as exc:
            errors.append(f"mymemory={exc}")
    raise RuntimeError("All free Japanese translation backends failed; " + "; ".join(errors))


def safe_translate_text(text, strict=False):
    if not isinstance(text, str) or not text.strip():
        return text
    if re.match(r"^https?://", text):
        return text
    if bad_error_text(text):
        raise RuntimeError(f"Source field contains an upstream error payload: {text[:100]!r}")
    key = hashlib.sha256(f"{base.CACHE_VERSION}|{text}".encode("utf-8")).hexdigest()
    cached = base.CACHE.get(key)
    if cached is not None:
        if target_quality_ok(text, cached, strict=strict):
            return cached
        base.CACHE.pop(key, None)

    out = []
    for part in base.chunks(text):
        if not part.strip():
            out.append(part)
            continue
        out.append(safe_translate_part(part, strict=strict))
        time.sleep(0.05)
    value = "".join(out)
    if not target_quality_ok(text, value, strict=strict):
        raise RuntimeError(f"Japanese translation failed quality gate: {text[:100]!r}")
    base.CACHE[key] = value
    return value


def extract_hkt_time(value):
    match = re.search(r"(?<!\d)([0-2]?\d:[0-5]\d)\s*HKT", str(value or ""), re.I)
    if not match:
        return None
    hh, mm = match.group(1).split(":", 1)
    hour = int(hh)
    if hour > 24 or (hour == 24 and mm != "00"):
        return None
    return f"{hour:02d}:{mm}"


def localize_last_updated(obj, original):
    raw = str(obj.get("lastUpdated") or "") if isinstance(obj, dict) else ""
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", raw)
    if match:
        y, mo, day, hh, mm = match.groups()
        return f"{y}年{int(mo)}月{int(day)}日 {hh}:{mm} HKT"
    return safe_translate_text(str(original or ""), strict=False)


def localize_next_update(original):
    value = extract_hkt_time(original)
    if value:
        return f"次回発行予定 {value} HKT"
    return safe_translate_text(str(original or ""), strict=False)


def localize_window(original):
    value = extract_hkt_time(original)
    if value:
        return f"{value} HKT 速報版"
    return safe_translate_text(str(original or ""), strict=False)


def safe_convert(obj, parent_key=""):
    if isinstance(obj, list):
        return [safe_convert(x, parent_key) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in base.KEEP_KEYS:
                out[k] = v
            elif k == "topics" and isinstance(v, list):
                out[k] = [base.translate_archive_topic(x) for x in v]
            elif k == "shortDate":
                out[k] = v
            elif k == "sections" and isinstance(v, list):
                out[k] = safe_convert(v, k)
            elif k == "lastUpdatedLabel":
                out[k] = localize_last_updated(obj, v)
            elif k == "nextUpdateLabel":
                out[k] = localize_next_update(v)
            elif k == "windowLabel":
                out[k] = localize_window(v)
            elif k in base.TRANSLATE_KEYS:
                out[k] = safe_translate_text(v, strict=k in STRICT_PROSE_KEYS) if isinstance(v, str) else safe_convert(v, k)
            else:
                out[k] = safe_convert(v, k)
        if isinstance(out.get("slug"), str) and out["slug"] in base.DESK_NAMES:
            out["title"] = base.DESK_NAMES[out["slug"]]
        if "shortDate" in out and isinstance(out.get("date"), str):
            out["shortDate"] = base.japanese_short_date(out["date"]) or out["shortDate"]
        return out
    if isinstance(obj, str) and parent_key in base.TRANSLATE_KEYS:
        return safe_translate_text(obj, strict=parent_key in STRICT_PROSE_KEYS)
    return obj


def prune_cache():
    removed = 0
    for key, value in list(base.CACHE.items()):
        text = str(value or "")
        if bad_error_text(text) or CHINESE_PROSE_RE.search(text):
            base.CACHE.pop(key, None)
            removed += 1
    print(f"TRANSLATION_CACHE_POISON_REMOVED {removed}")


def safe_existing_features_ok(name, data):
    if not _ORIGINAL_EXISTING_FEATURES_OK(name, data):
        return False
    issues = integrity.collect_issues(name, data)
    if issues:
        print(f"FAST_PATH_REJECTED {name}: {len(issues)} integrity issue(s)")
        return False
    return True


def main():
    prune_cache()
    base.translate_part = lambda part: safe_translate_part(part, strict=False)
    base.translate_text = lambda text: safe_translate_text(text, strict=False)
    base.convert = safe_convert
    base.existing_features_ok = safe_existing_features_ok
    base.main()


if __name__ == "__main__":
    main()
