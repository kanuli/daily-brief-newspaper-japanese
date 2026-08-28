#!/usr/bin/env python3
"""Self-healing full-parity sync for rolling/topic Japanese data.

The Cantonese repository remains the source of truth. A translation failure in
one rolling story is quarantined at that story instead of aborting the whole
file. Clean stories and current source metadata continue to publish. Degraded
files carry explicit deferred-owner metadata so maintenance can retry them on
later cycles without treating the file as fully repaired.

Large rolling files are also time-bounded per file. When the local translation
budget is exhausted, unprocessed owners are quarantined (not failed), the clean
current subset is published, and subsequent maintenance cycles resume from the
source fingerprints already translated. This prevents a large news hour from
turning into a GitHub Actions timeout loop.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import cantonese_snapshot as snapshot
import fast_safe_sync as fast
import furigana_safe_runtime
import local_metadata_overrides as metadata_overrides
import local_translation_runtime as runtime
import safe_sync as safe
import sync_and_translate as base
import sync_cantonese_layers as extra
import validate_content_integrity as integrity

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data"
DROP = object()


def _budget_seconds(name: str) -> int:
    """Keep the whole rebuild safely inside the workflow's 10-minute step."""
    if name == "desk-latest.json":
        return max(60, int(os.getenv("EXTRA_DESK_BUDGET_SECONDS", "330")))
    if name == "stocks-latest.json":
        return max(30, int(os.getenv("EXTRA_STOCKS_BUDGET_SECONDS", "90")))
    return max(30, int(os.getenv("EXTRA_TOPIC_BUDGET_SECONDS", "90")))


def _load_existing(name: str):
    path = OUT / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _index_stories(value, out=None):
    if out is None:
        out = {}
    if extra.story_like(value):
        out[str(value.get("id"))] = value
    if isinstance(value, dict):
        for child in value.values():
            _index_stories(child, out)
    elif isinstance(value, list):
        for child in value:
            _index_stories(child, out)
    return out


def _story_quality_ok(source_story, japanese_story) -> bool:
    if not isinstance(japanese_story, dict):
        return False
    for field in integrity.STORY_TEXT_FIELDS:
        source_text = source_story.get(field)
        target = japanese_story.get(field)
        if not isinstance(source_text, str) or not source_text.strip():
            continue
        strict = field in integrity.PROSE_FIELDS
        if not isinstance(target, str) or not safe.target_quality_ok(source_text, target, strict=strict):
            return False
    return True


def _stock_event_label(story: dict) -> str:
    kind = str(story.get("storyType") or "").upper()
    if "EARN" in kind or "RESULT" in kind:
        return "決算・業績"
    if "REGUL" in kind or "DISCLOS" in kind or "FILING" in kind:
        return "規制・公式開示"
    if "PRODUCT" in kind or "EVENT" in kind:
        return "製品・イベント"
    if "REVENUE" in kind or "CAPACITY" in kind:
        return "売上高・事業動向"
    if "ANALYST" in kind or "RATING" in kind:
        return "アナリスト動向"
    return "企業・市場動向"


def _stock_ticker_from_path(path: str) -> str:
    match = re.search(r"\.tickers\.([^\.\[]+)\.stories\[\d+\]", str(path or ""))
    return match.group(1) if match else "STOCK"


def _stock_minimum_fallback(source_story: dict, path: str, reason: str):
    """Publish a truthful Japanese minimum card when MT is unavailable.

    This is intentionally narrow: it uses only the ticker, source and verified
    event class already present in the source record. It never invents numbers,
    direction or details. The owner remains deferred, so later maintenance will
    retry and replace this minimum card with the full translation.
    """
    ticker = _stock_ticker_from_path(path)
    source_name = str(source_story.get("sourceName") or "").strip()
    if not source_name or base.likely_chinese_source(source_name):
        source_name = ticker
    event = _stock_event_label(source_story)
    value = {}
    for key in (
        "id", "storyType", "impact", "sourceName", "sourceUrl", "sources",
        "verificationMode", "verifiedAt", "primaryPublishedAt", "publishedAt",
        "updatedAt", "generatedAt",
    ):
        if key in source_story:
            value[key] = source_story[key]
    value["impactLabel"] = "確認済み情報"
    value["title"] = f"{ticker}：{source_name}で最新の{event}情報を確認"
    value["summary"] = (
        f"{source_name}を出典として、{event}に関する新しい検証済み情報を確認しました。"
        "詳細は出典資料の確認後に順次更新します。"
    )
    time_label = str(source_story.get("timeLabel") or "").strip()
    if time_label:
        value["timeLabel"] = time_label.replace("核實", "確認済み").replace("核实", "確認済み")
    value["translationStatus"] = "EDITORIAL_MINIMUM_FALLBACK"
    value["sourceItemFingerprint"] = extra.fingerprint(source_story)
    extra.decorate_story_tree(value, "rolling")
    print(
        "EXTRA_STOCK_EDITORIAL_MINIMUM_FALLBACK",
        f"ticker={ticker}",
        f"id={source_story.get('id')}",
        f"reason={reason}",
    )
    return value


def _translate_visible_string(source_text: str, old_value, parent_key: str, path: str, metadata_deferred: list[str], deadline: float):
    strict = parent_key in safe.STRICT_PROSE_KEYS
    if time.monotonic() >= deadline:
        if isinstance(old_value, str) and old_value.strip() and safe.target_quality_ok(source_text, old_value, strict=strict):
            metadata_deferred.append(path)
            return old_value
        metadata_deferred.append(path)
        print("EXTRA_SELF_HEAL_METADATA_BUDGET_DEFERRED", f"path={path}")
        return DROP
    try:
        return runtime.localize_or_translate(source_text, strict=strict)
    except Exception as exc:
        # Non-story chrome must not kill a whole rolling file. Reuse an already
        # validated Japanese value if available and mark it for automatic retry.
        if isinstance(old_value, str) and old_value.strip() and safe.target_quality_ok(source_text, old_value, strict=strict):
            metadata_deferred.append(path)
            print(
                "EXTRA_SELF_HEAL_METADATA_DEFERRED",
                f"path={path}",
                f"error={type(exc).__name__}:{str(exc)[:180]}",
            )
            return old_value
        if not base.likely_chinese_source(source_text):
            value = fast.localize_non_chinese(source_text)
            if safe.target_quality_ok(source_text, value, strict=strict):
                metadata_deferred.append(path)
                return value
        metadata_deferred.append(path)
        print(
            "EXTRA_SELF_HEAL_METADATA_OMITTED",
            f"path={path}",
            f"error={type(exc).__name__}:{str(exc)[:180]}",
        )
        return DROP


def _convert_node(source, old, file_name: str, path: str, old_by_id, deferred: set[str], metadata_deferred: list[str], deadline: float):
    if extra.story_like(source):
        story_id = str(source.get("id"))
        source_fp = extra.fingerprint(source)
        previous = old_by_id.get(story_id)
        can_reuse = bool(
            isinstance(previous, dict)
            and previous.get("sourceItemFingerprint") == source_fp
            and _story_quality_ok(source, previous)
        )
        if can_reuse:
            value = dict(previous)
            extra.decorate_story_tree(value, "rolling")
            print("EXTRA_SELF_HEAL_REUSE", f"file={file_name}", f"id={story_id}")
            return value

        if time.monotonic() >= deadline:
            deferred.add(story_id)
            if file_name == "stocks-latest.json":
                return _stock_minimum_fallback(source, path, "translation-budget-exhausted")
            print("EXTRA_SELF_HEAL_BUDGET_QUARANTINED", f"file={file_name}", f"id={story_id}")
            return DROP

        try:
            # Prewarm this owner only. A failure is caught here and cannot abort
            # translation of sibling stories.
            fast.prewarm_translations(source, f"{file_name}:{story_id}")
            value = safe.safe_convert(source)
            if not _story_quality_ok(source, value):
                raise RuntimeError("translated story failed source-aware quality gate")
            value["sourceItemFingerprint"] = source_fp
            extra.decorate_story_tree(value, "rolling")
            print("EXTRA_SELF_HEAL_TRANSLATED", f"file={file_name}", f"id={story_id}")
            return value
        except Exception as exc:
            deferred.add(story_id)
            print(
                "EXTRA_SELF_HEAL_QUARANTINED",
                f"file={file_name}",
                f"id={story_id}",
                f"error={type(exc).__name__}:{str(exc)[:220]}",
            )
            if file_name == "stocks-latest.json":
                return _stock_minimum_fallback(source, path, type(exc).__name__)
            return DROP

    if isinstance(source, list):
        output = []
        for index, child in enumerate(source):
            old_child = old[index] if isinstance(old, list) and index < len(old) else None
            value = _convert_node(
                child,
                old_child,
                file_name,
                f"{path}[{index}]",
                old_by_id,
                deferred,
                metadata_deferred,
                deadline,
            )
            if value is not DROP:
                output.append(value)
        return output

    if isinstance(source, dict):
        output = {}
        old_dict = old if isinstance(old, dict) else {}
        for key, child in source.items():
            if key in base.KEEP_KEYS or key in {
                "generatedAt", "mode", "editorialStandardVersion", "contentVersion",
                "sourceFingerprint", "translationSchemaVersion", "language",
                "translationSource", "sourceFile", "sourceParityMode",
            }:
                output[key] = child
                continue
            child_path = f"{path}.{key}"
            if isinstance(child, str) and key in base.TRANSLATE_KEYS:
                value = _translate_visible_string(
                    child,
                    old_dict.get(key),
                    key,
                    child_path,
                    metadata_deferred,
                    deadline,
                )
            else:
                value = _convert_node(
                    child,
                    old_dict.get(key),
                    file_name,
                    child_path,
                    old_by_id,
                    deferred,
                    metadata_deferred,
                    deadline,
                )
            if value is not DROP:
                output[key] = value
        return output

    if isinstance(source, str) and path.rsplit(".", 1)[-1] in base.TRANSLATE_KEYS:
        key = path.rsplit(".", 1)[-1]
        return _translate_visible_string(source, old, key, path, metadata_deferred, deadline)
    return source


def sync_file(name: str, source) -> bool:
    source_hash = extra.fingerprint(source)
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing(name)

    if (
        isinstance(existing, dict)
        and existing.get("language") == "ja"
        and existing.get("translationSchemaVersion") == extra.SCHEMA
        and existing.get("sourceFingerprint") == source_hash
        and not existing.get("translationDegraded")
        and int(existing.get("translationDeferredCount") or 0) == 0
    ):
        print("EXTRA_SELF_HEAL_FAST_PATH", name)
        return False

    budget = _budget_seconds(name)
    started = time.monotonic()
    deadline = started + budget
    old_by_id = _index_stories(existing or {})
    deferred: set[str] = set()
    metadata_deferred: list[str] = []
    translated = _convert_node(
        source,
        existing,
        name,
        "$",
        old_by_id,
        deferred,
        metadata_deferred,
        deadline,
    )
    if translated is DROP or not isinstance(translated, dict):
        raise RuntimeError(f"Self-healing extra sync could not construct {name}")

    story_count = len(_index_stories(translated))
    source_story_count = len(_index_stories(source))
    if source_story_count and story_count == 0:
        raise RuntimeError(f"Self-healing guard refused empty rolling publication: {name}")

    elapsed = int(time.monotonic() - started)
    budget_exhausted = time.monotonic() >= deadline
    extra.decorate_story_tree(translated, "rolling")
    translated["language"] = "ja"
    translated["translationSource"] = "kanuli/daily-brief-newspaper"
    translated["sourceFile"] = name
    translated["sourceFingerprint"] = source_hash
    translated["translationSchemaVersion"] = extra.SCHEMA
    translated["sourceParityMode"] = "owner-quarantine-v1"
    translated["translationDegraded"] = bool(deferred or metadata_deferred)
    translated["translationDeferredCount"] = len(deferred) + len(metadata_deferred)
    translated["translationDeferredIds"] = sorted(deferred)
    translated["translationDeferredMetadata"] = metadata_deferred[:80]
    translated["translationRecoveryMode"] = "owner-quarantine-v1"
    translated["translationBudgetSeconds"] = budget
    translated["translationElapsedSeconds"] = elapsed
    translated["translationBudgetExhausted"] = budget_exhausted

    path.write_text(json.dumps(translated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Persist successful work after every source file. A later timeout/crash must
    # never throw away translations that a subsequent maintenance cycle can reuse.
    runtime.checkpoint_cache(f"self-healing-extra-{name.replace('/', '-')}")
    print(
        "EXTRA_SELF_HEAL_PUBLISHED_CANDIDATE",
        f"file={name}",
        f"stories={story_count}/{source_story_count}",
        f"deferred_stories={len(deferred)}",
        f"deferred_metadata={len(metadata_deferred)}",
        f"elapsed={elapsed}s",
        f"budget={budget}s",
        f"budget_exhausted={budget_exhausted}",
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

    names = ["desk-latest.json", "stocks-latest.json", f"topic-more/{date}.json"]
    changed = []
    for name in names:
        source = snapshot.load_json(name, optional=name.startswith("topic-more/"))
        if source is None:
            continue
        if sync_file(name, source):
            changed.append(name)

    folder = OUT / "topic-more"
    if folder.is_dir():
        for old in folder.glob("*.json"):
            if old.name != f"{date}.json":
                old.unlink()

    runtime.checkpoint_cache("self-healing-extra-sync")
    print(
        "EXTRA_SELF_HEAL_SYNC_OK",
        f"snapshot={snapshot.snapshot_commit()}",
        f"date={date}",
        f"changed={','.join(changed) if changed else 'none'}",
    )


if __name__ == "__main__":
    main()
