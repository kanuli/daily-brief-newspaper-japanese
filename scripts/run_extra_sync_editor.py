#!/usr/bin/env python3
"""Editor-in-Chief runner for resilient rolling Japanese news publication.

Critical reader-facing layers are processed before the oversized desk feed so
one expensive queue cannot starve stocks or current topic pages. Individual
layer failures are isolated: a failed layer remains quarantined while healthy
layers continue through quality review and publication.
"""
from __future__ import annotations

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


def _prioritize_topic(source):
    """Put manga/anime first because that page depends heavily on topic-more."""
    if not isinstance(source, dict):
        return source
    articles = source.get("articles")
    if not isinstance(articles, list):
        return source
    prioritized = sorted(
        enumerate(articles),
        key=lambda pair: (
            0 if str(pair[1].get("section") or "") == "manga-anime" else 1,
            pair[0],
        ),
    )
    copy = dict(source)
    copy["articles"] = [article for _, article in prioritized]
    return copy


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
    # Reader-critical layers first. The large desk feed is deliberately last.
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
        if name == topic_name:
            source = _prioritize_topic(source)
        try:
            if healing.sync_file(name, source):
                changed.append(name)
        except Exception as exc:
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
    )

    # A partial failure must not block healthy sections. Fail only when every
    # attempted layer failed and therefore no useful repair candidate exists.
    if attempted and len(failures) == attempted:
        raise RuntimeError("Every rolling layer failed; refusing false-success publication")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
