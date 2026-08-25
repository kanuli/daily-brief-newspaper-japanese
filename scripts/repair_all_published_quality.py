#!/usr/bin/env python3
"""Repair every published Japanese story layer against the Cantonese source.

This is the exhaustive quality-repair pass used when generic Japanese-only
validation is not enough.  It repairs core Daily/Live, rolling desks, tracked
stocks, today's topic-more and any older published topic-more file that still
exists in the same frozen Cantonese source commit.

The key difference from the normal repair workers is source-aware entity
validation.  A translation may look grammatical yet still be unusable when a
named entity has been hallucinated (for example 輝達 becoming an unrelated
company name).  Known high-value entity anchors must survive translation in an
accepted Japanese/English form.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import cantonese_snapshot as snapshot
import repair_garbled_core as core_repair
import repair_garbled_extra_layers as extra_repair
import safe_sync as safe
import local_translation_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_REPO = "kanuli/daily-brief-newspaper"

# Source token -> acceptable target spellings.  Keep this deliberately focused
# on names where translating the Han alias literally can create a false entity.
ENTITY_ANCHORS = {
    "輝達": ("Nvidia", "NVIDIA", "エヌビディア"),
    "英偉達": ("Nvidia", "NVIDIA", "エヌビディア"),
    "Nvidia": ("Nvidia", "NVIDIA", "エヌビディア"),
    "NVIDIA": ("Nvidia", "NVIDIA", "エヌビディア"),
    "蘋果": ("Apple", "アップル"),
    "Apple": ("Apple", "アップル"),
    "微軟": ("Microsoft", "マイクロソフト"),
    "Microsoft": ("Microsoft", "マイクロソフト"),
    "谷歌": ("Google", "グーグル"),
    "Google": ("Google", "グーグル"),
    "台積電": ("TSMC", "台湾積体電路", "台湾セミコンダクター"),
    "TSMC": ("TSMC", "台湾積体電路", "台湾セミコンダクター"),
    "Palantir": ("Palantir", "パランティア"),
    "OpenAI": ("OpenAI", "オープンAI"),
    "Reuters": ("Reuters", "ロイター"),
    "Bloomberg": ("Bloomberg", "ブルームバーグ"),
    "Manchester United": ("Manchester United", "マンチェスター・ユナイテッド"),
}

# Corruption shapes seen in production that can contain plenty of kana/kanji
# and therefore evade a simple "is this Japanese" test.
REPEATED_PARTICLE_RE = re.compile(r"の{5,}")
ASCII_ART_RE = re.compile(r"(?:━{4,}|─{5,}|═{5,}|[\\/@]{3,})")
WEIRD_ROMAN_FRAGMENT_RE = re.compile(r"(?<![A-Za-z])[a-z]{2,}(?![A-Za-z])")
ROMAN_ALLOW = {"ai", "app", "apps", "web", "live", "online", "email", "vs", "km", "kg", "cm", "mm"}


def entity_mismatch(source_text: str, target_text: str) -> str | None:
    source = str(source_text or "")
    target = str(target_text or "")
    for token, accepted in ENTITY_ANCHORS.items():
        if token not in source:
            continue
        if any(name in target for name in accepted):
            continue
        return f"entity anchor {token!r} disappeared or changed"
    return None


def obvious_gibberish(target_text: str) -> str | None:
    text = str(target_text or "")
    if REPEATED_PARTICLE_RE.search(text):
        return "impossible repeated Japanese particle run"
    if ASCII_ART_RE.search(text):
        return "ASCII/box-art corruption"
    for match in WEIRD_ROMAN_FRAGMENT_RE.finditer(text):
        word = match.group(0).lower()
        if word not in ROMAN_ALLOW:
            return f"unexpected lowercase roman fragment {word!r}"
    return None


def enhanced_bad_translation(source_text: str, japanese_text: str, strict: bool) -> bool:
    # Retain every structural, numeric, Han-overlap and mixed-language check
    # already implemented by the production quality gate.
    if not isinstance(japanese_text, str) or not japanese_text.strip():
        return True
    if not safe.target_quality_ok(source_text, japanese_text, strict=strict):
        return True
    if entity_mismatch(source_text, japanese_text):
        return True
    if obvious_gibberish(japanese_text):
        return True
    return False


def fetch_topic_from_snapshot_commit(name: str):
    commit = snapshot.snapshot_commit()
    if not commit:
        raise RuntimeError("missing frozen Cantonese snapshot commit")
    url = f"https://raw.githubusercontent.com/{SOURCE_REPO}/{commit}/data/{name}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "daily-brief-newspaper-japanese-full-quality-repair"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def repair_historical_topics() -> int:
    folder = DATA / "topic-more"
    if not folder.is_dir():
        return 0
    repaired = 0
    current_date = str((snapshot.load_json("latest.json") or {}).get("date") or "")
    for path in sorted(folder.glob("*.json")):
        if path.stem == current_date:
            continue
        name = f"topic-more/{path.name}"
        source = fetch_topic_from_snapshot_commit(name)
        if source is None:
            print("FULL_QUALITY_TOPIC_SKIP", name, "no-source-counterpart")
            continue
        repaired += extra_repair.repair_file(name, source)
    return repaired


def main():
    # Force both existing repair workers to use the stronger source-aware gate.
    core_repair.bad_translation = enhanced_bad_translation
    extra_repair.bad_translation = enhanced_bad_translation

    print("FULL_QUALITY_REPAIR_PHASE core")
    core_repair.main()
    print("FULL_QUALITY_REPAIR_PHASE rolling-current")
    extra_repair.main()
    print("FULL_QUALITY_REPAIR_PHASE historical-topics")
    historical = repair_historical_topics()
    runtime.checkpoint_cache("full-published-quality-repair")
    print("FULL_PUBLISHED_QUALITY_REPAIR_OK", f"historical_topic_fields={historical}")


if __name__ == "__main__":
    main()
