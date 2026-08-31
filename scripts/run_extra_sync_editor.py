#!/usr/bin/env python3
"""Editor-in-Chief runner for resilient rolling Japanese news publication.

Publication availability is a hard requirement. The source newsroom may keep
large rolling corpora, but the Japanese site must first secure a small current
reader-facing edition for every desk/ticker before spending translation budget
on depth. One layer or one oversized queue must never starve another page.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import cantonese_snapshot as snapshot
import furigana_safe_runtime
import local_metadata_overrides as metadata_overrides
import local_translation_runtime as runtime
import safe_sync as safe
import sync_and_translate as base
import sync_cantonese_layers as extra
import self_healing_extra_sync as healing

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data"

DESK_LABELS = {
    "world": "世界",
    "asia": "アジア",
    "hong-kong": "香港",
    "japan": "日本",
    "market-economy": "マーケット・経済",
    "technology": "AI・テクノロジー",
    "manga-anime": "漫画・アニメ",
    "manchester-united": "マンチェスター・ユナイテッド",
    "football": "サッカー",
}


def _story_slugs(story):
    if not isinstance(story, dict):
        return set()
    slugs = {str(story.get("desk") or ""), str(story.get("section") or "")}
    slugs.update(str(x) for x in (story.get("deskSlugs") or []) if x)
    return {x for x in slugs if x}


def _prioritize_topic(source):
    """Put manga/anime first because Daily may legitimately publish zero there."""
    if not isinstance(source, dict):
        return source
    articles = source.get("articles")
    if not isinstance(articles, list):
        return source
    prioritized = sorted(
        enumerate(articles),
        key=lambda pair: (
            0 if "manga-anime" in _story_slugs(pair[1]) else 1,
            pair[0],
        ),
    )
    copy = dict(source)
    copy["articles"] = [article for _, article in prioritized]
    return copy


def _compact_desk(source):
    """Guarantee current coverage for every desk before translating extra depth."""
    if not isinstance(source, dict) or not isinstance(source.get("desks"), dict):
        return source
    per_desk = max(1, int(os.getenv("EXTRA_DESK_STORIES_PER_DESK", "1")))
    copy = dict(source)
    compact = {}
    source_counts = {}
    selected_counts = {}
    for desk, items in source["desks"].items():
        rows = list(items) if isinstance(items, list) else []
        source_counts[str(desk)] = len(rows)
        compact[str(desk)] = rows[:per_desk]
        selected_counts[str(desk)] = len(compact[str(desk)])
    copy["desks"] = compact
    copy["editorSelectionMode"] = "minimum-guaranteed-edition-per-desk"
    copy["sourceDeskStoryCounts"] = source_counts
    copy["selectedDeskStoryCounts"] = selected_counts
    copy["selectedStoriesPerDeskLimit"] = per_desk
    return copy


def _compact_stocks(source):
    """Keep the newest available story per tracked ticker as the guaranteed edition."""
    if not isinstance(source, dict) or not isinstance(source.get("tickers"), dict):
        return source
    per_ticker = max(1, int(os.getenv("EXTRA_STOCK_STORIES_PER_TICKER", "1")))
    copy = dict(source)
    tickers = {}
    source_counts = {}
    selected_counts = {}
    for ticker, info in source["tickers"].items():
        if not isinstance(info, dict):
            tickers[ticker] = info
            continue
        item = dict(info)
        rows = list(info.get("stories") or []) if isinstance(info.get("stories"), list) else []
        source_counts[str(ticker)] = len(rows)
        item["stories"] = rows[:per_ticker]
        selected_counts[str(ticker)] = len(item["stories"])
        tickers[ticker] = item
    copy["tickers"] = tickers
    copy["editorSelectionMode"] = "minimum-guaranteed-edition-per-ticker"
    copy["sourceTickerStoryCounts"] = source_counts
    copy["selectedTickerStoryCounts"] = selected_counts
    copy["selectedStoriesPerTickerLimit"] = per_ticker
    return copy


def _prepare_source(name: str, source):
    if name == "stocks-latest.json":
        return _compact_stocks(source)
    if name == "desk-latest.json":
        return _compact_desk(source)
    if name.startswith("topic-more/"):
        return _prioritize_topic(source)
    return source


def _safe_source_name(story: dict, desk: str) -> str:
    value = str(story.get("sourceName") or "").strip()
    if value and not base.likely_chinese_source(value):
        return value
    sources = story.get("sources") or []
    if isinstance(sources, list):
        names = [str(item.get("name") or "").strip() for item in sources if isinstance(item, dict)]
        names = [name for name in names if name and not base.likely_chinese_source(name)]
        if names:
            return "／".join(names[:2])
    return DESK_LABELS.get(desk, "報道機関")


def _desk_minimum_story(source_story: dict, desk: str) -> dict:
    """Create a source-backed Japanese availability card without inventing facts."""
    label = DESK_LABELS.get(desk, "ニュース")
    source_name = _safe_source_name(source_story, desk)
    value = {}
    for key in (
        "id", "desk", "status", "sourceName", "sourceUrl", "sources", "deskSlugs",
        "verificationMode", "verifiedAt", "primaryPublishedAt", "publishedAt",
        "updatedAt", "generatedAt", "image",
    ):
        if key in source_story:
            value[key] = source_story[key]
    value["desk"] = desk
    value["deskSlugs"] = list(source_story.get("deskSlugs") or [desk])
    value["section"] = label
    value["sectionLabel"] = label
    value["title"] = f"{label}：{source_name}の最新確認済みニュース"
    value["dek"] = "出典で確認済みの最新情報を先行掲載しています。"
    value["summary"] = (
        f"{source_name}を出典として、この分類の最新ニュースを確認しました。"
        "完全な日本語本文は自動復旧処理で順次更新します。"
    )
    time_label = str(source_story.get("timeLabel") or "").strip()
    if time_label:
        value["timeLabel"] = time_label.replace("核實", "確認済み").replace("核实", "確認済み")
    value["translationStatus"] = "EDITORIAL_MINIMUM_FALLBACK"
    value["sourceItemFingerprint"] = extra.fingerprint(source_story)
    extra.decorate_story_tree(value, "rolling")
    return value


def _write_desk_minimum_fallback(source: dict, reason: str) -> bool:
    """Fail open for availability but fail closed on provenance and recovery state."""
    if not isinstance(source, dict) or not isinstance(source.get("desks"), dict):
        return False
    translated = {key: value for key, value in source.items() if key != "desks"}
    desks = {}
    deferred = []
    for desk, rows in source["desks"].items():
        selected = list(rows) if isinstance(rows, list) else []
        if not selected:
            desks[str(desk)] = []
            continue
        story = selected[0]
        if not isinstance(story, dict) or not story.get("id"):
            desks[str(desk)] = []
            continue
        desks[str(desk)] = [_desk_minimum_story(story, str(desk))]
        deferred.append(str(story.get("id")))
    if not any(desks.values()):
        return False
    translated["desks"] = desks
    translated["language"] = "ja"
    translated["translationSource"] = "kanuli/daily-brief-newspaper"
    translated["sourceFile"] = "desk-latest.json"
    translated["sourceFingerprint"] = extra.fingerprint(source)
    translated["translationSchemaVersion"] = extra.SCHEMA
    translated["sourceParityMode"] = "editorial-minimum-fallback-v1"
    translated["translationDegraded"] = True
    translated["translationDeferredCount"] = len(deferred)
    translated["translationDeferredIds"] = deferred
    translated["translationDeferredMetadata"] = []
    translated["translationRecoveryMode"] = "editorial-minimum-fallback-v1"
    translated["editorSelectionMode"] = "minimum-guaranteed-edition-per-desk"
    path = OUT / "desk-latest.json"
    path.write_text(json.dumps(translated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "EXTRA_DESK_EDITORIAL_MINIMUM_FALLBACK",
        f"stories={len(deferred)}",
        f"reason={reason[:240]}",
        "recovery_required=true",
    )
    return True


def main():
    base.likely_chinese_source = extra.needs_cantonese_translation
    base.TRANSLATE_KEYS.update({"impactLabel"})
    furigana_safe_runtime.install()
    metadata_overrides.install(runtime)
    runtime.install()
    safe.prune_cache()

    latest = snapshot.load_json("latest.json")
    date = str((latest or {}).get("date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise RuntimeError(f"Invalid current snapshot date: {date!r}")

    topic_name = f"topic-more/{date}.json"
    # Critical small layers first. The now-compacted all-desk guarantee comes
    # last so stocks and Daily-gap topic coverage can never be starved.
    names = ["stocks-latest.json", topic_name, "desk-latest.json"]
    changed: list[str] = []
    failures: list[str] = []
    attempted = 0

    for name in names:
        source = snapshot.load_json(name, optional=name.startswith("topic-more/"))
        if source is None:
            print("EXTRA_EDITOR_SOURCE_OPTIONAL_MISSING", f"file={name}")
            continue
        attempted += 1
        source = _prepare_source(name, source)
        try:
            if healing.sync_file(name, source):
                changed.append(name)
        except Exception as exc:
            if name == "desk-latest.json":
                try:
                    if _write_desk_minimum_fallback(source, f"{type(exc).__name__}:{exc}"):
                        changed.append(name)
                        runtime.checkpoint_cache("editor-desk-minimum-fallback")
                        continue
                except Exception as fallback_exc:
                    print(
                        "EXTRA_DESK_EDITORIAL_MINIMUM_FALLBACK_FAILED",
                        f"error={type(fallback_exc).__name__}:{str(fallback_exc)[:240]}",
                    )
            failures.append(name)
            print(
                "EXTRA_EDITOR_LAYER_FAILED_ISOLATED",
                f"file={name}",
                f"error={type(exc).__name__}:{str(exc)[:300]}",
            )
            runtime.checkpoint_cache(f"editor-isolated-failure-{name.replace('/', '-')}")

    # Never erase historical topic-more files unless today's replacement exists.
    current_topic_path = OUT / topic_name
    folder = OUT / "topic-more"
    if current_topic_path.is_file() and folder.is_dir():
        for old in folder.glob("*.json"):
            if old.name != f"{date}.json":
                old.unlink()
    elif folder.is_dir():
        print("EXTRA_EDITOR_TOPIC_CLEANUP_SKIPPED", f"missing_current={topic_name}")

    runtime.checkpoint_cache("editor-resilient-extra-sync")
    print(
        "EXTRA_EDITOR_SYNC_RESULT",
        f"snapshot={snapshot.snapshot_commit()}",
        f"date={date}",
        f"attempted={attempted}",
        f"changed={','.join(changed) if changed else 'none'}",
        f"failures={','.join(failures) if failures else 'none'}",
        "minimum_desk_edition=true",
        "minimum_stock_edition=true",
    )

    # A partial failure must not block healthy sections. Fail only when every
    # attempted layer failed and therefore no useful repair candidate exists.
    if attempted and len(failures) == attempted:
        raise RuntimeError("Every rolling layer failed; refusing false-success publication")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
