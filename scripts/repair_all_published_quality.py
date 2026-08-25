#!/usr/bin/env python3
"""Repair every published Japanese layer against the Cantonese source.

This is the exhaustive quality-repair pass used when Japanese-only validation
is not enough. It repairs Daily/Live, rolling desks, tracked stocks, topic-more,
and translated metadata such as section subtitles and impact labels.

The pass is source-aware. A target can look Japanese yet still be unusable when
a named entity or the meaning was hallucinated. High-value entity anchors must
survive translation in an accepted Japanese/English form.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import cantonese_snapshot as snapshot
import local_translation_runtime as runtime
import repair_garbled_core as core_repair
import repair_garbled_extra_layers as extra_repair
import safe_sync as safe
import sync_and_translate as base
import sync_cantonese_layers as extra
import validate_content_integrity as integrity

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_REPO = "kanuli/daily-brief-newspaper"

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

REPEATED_PARTICLE_RE = re.compile(r"の{5,}")
ASCII_ART_RE = re.compile(r"(?:━{4,}|─{5,}|═{5,}|[\\/@]{3,})")
REPEATED_TOKEN_RE = re.compile(r"(.{2,8})(?:\s+\1){2,}")
WEIRD_ROMAN_FRAGMENT_RE = re.compile(r"(?<![A-Za-z])[a-z]{2,}(?![A-Za-z])")
ROMAN_ALLOW = {
    "ai", "app", "apps", "web", "live", "online", "email", "vs",
    "km", "kg", "cm", "mm", "am", "pm", "fps", "bps",
}
TRANSLATABLE_METADATA_KEYS = set(base.TRANSLATE_KEYS) | {"impactLabel"}


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
    if REPEATED_TOKEN_RE.search(text):
        return "repeated placeholder-like phrase"
    for match in WEIRD_ROMAN_FRAGMENT_RE.finditer(text):
        word = match.group(0).lower()
        if word not in ROMAN_ALLOW:
            return f"unexpected lowercase roman fragment {word!r}"
    return None


def enhanced_bad_translation(source_text: str, japanese_text: str, strict: bool) -> bool:
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


def repair_metadata_file(name: str, source) -> int:
    """Repair translated strings anywhere in a published JSON tree.

    Existing story repair workers cover the main article fields. This second
    recursive pass catches page metadata that used to escape validation, such as
    section subtitles, labels and impact labels. Story decoration is regenerated
    whenever a visible story field changes.
    """
    path = DATA / name
    if not path.is_file() or source is None:
        return 0
    local = json.loads(path.read_text(encoding="utf-8"))
    repaired = 0

    def walk(local_value, source_value, in_story=False):
        nonlocal repaired
        story_here = in_story or (extra.story_like(local_value) and extra.story_like(source_value))
        story_changed = False

        if isinstance(local_value, dict) and isinstance(source_value, dict):
            for key, source_child in source_value.items():
                if key not in local_value:
                    continue
                local_child = local_value[key]
                if (
                    key in TRANSLATABLE_METADATA_KEYS
                    and isinstance(source_child, str)
                    and source_child.strip()
                    and isinstance(local_child, str)
                ):
                    strict = key in integrity.PROSE_FIELDS
                    if enhanced_bad_translation(source_child, local_child, strict):
                        print(
                            "FULL_METADATA_REPAIR_FIELD",
                            f"file={name}",
                            f"key={key}",
                            f"old={local_child[:90]!r}",
                        )
                        local_value[key] = extra_repair.repair_value(source_child, strict)
                        repaired += 1
                        story_changed = story_changed or story_here
                elif isinstance(local_child, (dict, list)) and isinstance(source_child, type(local_child)):
                    child_changed = walk(local_child, source_child, story_here)
                    story_changed = story_changed or child_changed

            if story_here and story_changed:
                extra.decorate_story_tree(local_value, "rolling")
            return story_changed

        if isinstance(local_value, list) and isinstance(source_value, list):
            any_changed = False
            for local_child, source_child in zip(local_value, source_value):
                if isinstance(local_child, (dict, list)) and isinstance(source_child, type(local_child)):
                    any_changed = walk(local_child, source_child, story_here) or any_changed
            return any_changed
        return False

    walk(local, source)
    if repaired:
        path.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("FULL_METADATA_REPAIR_RESULT", name, f"fields={repaired}")
    return repaired


def repair_historical_topics() -> tuple[int, int]:
    folder = DATA / "topic-more"
    if not folder.is_dir():
        return 0, 0
    story_fields = 0
    metadata_fields = 0
    current_date = str((snapshot.load_json("latest.json") or {}).get("date") or "")
    for path in sorted(folder.glob("*.json")):
        if path.stem == current_date:
            continue
        name = f"topic-more/{path.name}"
        source = fetch_topic_from_snapshot_commit(name)
        if source is None:
            print("FULL_QUALITY_TOPIC_SKIP", name, "no-source-counterpart")
            continue
        story_fields += extra_repair.repair_file(name, source)
        metadata_fields += repair_metadata_file(name, source)
    return story_fields, metadata_fields


def main():
    core_repair.bad_translation = enhanced_bad_translation
    extra_repair.bad_translation = enhanced_bad_translation

    print("FULL_QUALITY_REPAIR_PHASE core")
    core_repair.main()

    print("FULL_QUALITY_REPAIR_PHASE rolling-current")
    extra_repair.main()

    current_sources = {
        "desk-latest.json": snapshot.load_json("desk-latest.json"),
        "stocks-latest.json": snapshot.load_json("stocks-latest.json"),
    }
    latest = snapshot.load_json("latest.json") or {}
    date = str(latest.get("date") or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        topic_name = f"topic-more/{date}.json"
        topic_source = snapshot.load_json(topic_name, optional=True)
        if topic_source is not None:
            current_sources[topic_name] = topic_source

    metadata_total = 0
    for name, source in current_sources.items():
        metadata_total += repair_metadata_file(name, source)

    print("FULL_QUALITY_REPAIR_PHASE historical-topics")
    historical_story, historical_metadata = repair_historical_topics()
    runtime.checkpoint_cache("full-published-quality-repair")
    print(
        "FULL_PUBLISHED_QUALITY_REPAIR_OK",
        f"metadata_fields={metadata_total}",
        f"historical_story_fields={historical_story}",
        f"historical_metadata_fields={historical_metadata}",
    )


if __name__ == "__main__":
    main()
