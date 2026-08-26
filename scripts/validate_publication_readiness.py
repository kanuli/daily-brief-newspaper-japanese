#!/usr/bin/env python3
"""Publication-readiness gate that deliberately permits asynchronous F3 audio.

News publication must be blocked by bad Japanese, broken schemas/references, or
missing learner-facing text. It must NOT be blocked merely because the server
has not generated the MP3/timing asset or final F3 metadata yet. Full audio
completeness remains the responsibility of validate_site.py --data-only and the
F3 audio health workflows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import validate_content_integrity as integrity

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
KANA_RE = re.compile(r"[\u3040-\u30ff]")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
EXPECTED_AUDIO_SPEED = 0.72
EXPECTED_DELIVERY_PROFILE = "jp-tv-news-semantic-v4"


def fail(message: str) -> None:
    raise SystemExit("PUBLICATION_READINESS_FAIL: " + message)


def load(name: str) -> dict:
    path = DATA / name
    if not path.is_file():
        fail(f"missing data/{name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid data/{name}: {exc}")


def paragraphs(item: dict) -> list[str]:
    raw = str(item.get("body") or item.get("summary") or "")
    return [p for p in re.split(r"\n\s*\n", raw) if p.strip()]


def check_item(group: str, item: dict, warnings: list[str]) -> None:
    aid = str(item.get("id") or "").strip()
    if not aid:
        fail(f"{group}: article/item id missing")
    title = str(item.get("title") or "").strip()
    if not title:
        fail(f"{group}:{aid}: title missing")
    visible = " ".join(str(item.get(k) or "") for k in ("title", "dek", "summary", "body", "context", "why", "watchNext"))
    if len(visible.strip()) < 10 or not KANA_RE.search(visible):
        fail(f"{group}:{aid}: learner-facing copy does not look Japanese")

    furigana = item.get("furigana") or {}
    if not isinstance(furigana, dict):
        fail(f"{group}:{aid}: furigana object missing")
    if HAN_RE.search(title) and "<ruby>" not in str(furigana.get("title") or ""):
        fail(f"{group}:{aid}: title furigana missing")
    if len(furigana.get("bodyParagraphs") or []) != len(paragraphs(item)):
        fail(f"{group}:{aid}: body furigana paragraph mismatch")

    expected_audio = f"audio/{group}/{aid}.mp3"
    expected_timing = f"audio/timing/{group}/{aid}.json"
    if item.get("audio") != expected_audio:
        fail(f"{group}:{aid}: audio path metadata mismatch")
    if item.get("timing") != expected_timing:
        fail(f"{group}:{aid}: timing path metadata mismatch")

    audio_exists = (ROOT / expected_audio).is_file()
    timing_exists = (ROOT / expected_timing).is_file()

    # Speed/profile are final F3 metadata. Before synthesis they may legitimately
    # be absent. Once present, however, they must match the approved delivery
    # profile; a conflicting value is a real publication-integrity problem.
    speed_raw = item.get("audioSpeed")
    if speed_raw not in (None, ""):
        try:
            speed = float(speed_raw)
        except Exception:
            fail(f"{group}:{aid}: invalid audioSpeed metadata")
        if abs(speed - EXPECTED_AUDIO_SPEED) > 0.001:
            fail(f"{group}:{aid}: audioSpeed metadata mismatch")
    else:
        warnings.append(f"{group}:{aid}: audioSpeed pending")

    profile = item.get("audioDeliveryProfile")
    if profile not in (None, ""):
        if profile != EXPECTED_DELIVERY_PROFILE:
            fail(f"{group}:{aid}: audioDeliveryProfile metadata mismatch")
    else:
        warnings.append(f"{group}:{aid}: audioDeliveryProfile pending")

    # Missing physical audio/timing is a valid temporary state. The frontend's
    # F3 voice-status layer will show 音声準備中 until the manifest/assets arrive.
    if not audio_exists:
        warnings.append(f"{group}:{aid}: audio pending")
    if not timing_exists:
        warnings.append(f"{group}:{aid}: timing pending")


def check_archive(data: dict) -> None:
    if data.get("language") != "ja":
        fail("archive.json language != ja")
    editions = data.get("editions") or []
    if not editions:
        fail("archive editions are empty")
    for index, edition in enumerate(editions):
        headline = str(edition.get("headline") or "").strip()
        if not headline or not KANA_RE.search(headline):
            fail(f"archive edition {index}: headline missing/not Japanese")
        topics = edition.get("topics") or []
        ruby_topics = edition.get("furiganaTopics") or []
        if not topics or len(topics) != len(ruby_topics):
            fail(f"archive edition {index}: topic/furigana structure mismatch")


def main() -> int:
    latest = load("latest.json")
    live = load("live.json")
    archive = load("archive.json")

    for name, data in (("latest.json", latest), ("live.json", live), ("archive.json", archive)):
        issues = integrity.collect_issues(name, data)
        if issues:
            fail(f"{name}: {issues[0]}")

    if latest.get("language") != "ja":
        fail("latest.json language != ja")
    if live.get("language") != "ja":
        fail("live.json language != ja")

    daily = latest.get("articles") or []
    live_items = live.get("items") or []
    if not daily:
        fail("Daily articles are empty")
    if not live_items:
        fail("Live items are empty")

    warnings: list[str] = []
    for item in daily:
        check_item("daily", item, warnings)
    for item in live_items:
        check_item("live", item, warnings)
    check_archive(archive)

    for warning in warnings[:100]:
        print("PUBLICATION_AUDIO_PENDING -", warning)
    if len(warnings) > 100:
        print(f"PUBLICATION_AUDIO_PENDING - ... and {len(warnings) - 100} more")
    print(
        f"PUBLICATION_READINESS_OK daily={len(daily)} live={len(live_items)} "
        f"pending_warnings={len(warnings)} asynchronous_audio_allowed=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
