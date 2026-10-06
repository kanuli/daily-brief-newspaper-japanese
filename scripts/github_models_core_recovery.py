#!/usr/bin/env python3
"""Independent targeted GitHub Models recovery for degraded Daily/Live fields.

This final fallback deliberately avoids torch/transformers/local OPUS-MT.
The emergency rebuild establishes current source structure first; this script
repairs only fields that still fail the existing Japanese newsroom quality gates,
then rebuilds furigana/audio metadata and clears degraded markers only after a
full source-linked revalidation succeeds.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

import cantonese_snapshot as snapshot
import furigana_safe_runtime
import newsroom_quality
import safe_sync as safe
import sync_and_translate as base
import validate_content_integrity as integrity


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CORE_FILES = ("latest.json", "live.json")
CORE_FIELDS = ("section", "sectionLabel") + integrity.STORY_TEXT_FIELDS
BAD_STATUSES = {"EDITORIAL_MINIMUM_FALLBACK", "TRANSLATION_FAILED", "TRANSLATION_DEGRADED"}

API = os.getenv(
    "GITHUB_MODELS_ENDPOINT",
    "https://models.github.ai/inference/chat/completions",
)
MODELS = tuple(
    x.strip()
    for x in os.getenv(
        "GITHUB_MODELS_TRANSLATION_MODELS",
        "openai/gpt-4o,openai/gpt-4o-mini",
    ).split(",")
    if x.strip()
)
TOKEN = os.getenv("GITHUB_MODELS_TOKEN") or os.getenv("GITHUB_TOKEN")


def iter_stories(value):
    if isinstance(value, dict):
        if value.get("id") and (value.get("title") or value.get("summary") or value.get("body")):
            yield value
        for child in value.values():
            yield from iter_stories(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_stories(child)


def index_stories(value):
    return {
        str(story.get("id")): story
        for story in iter_stories(value)
        if story.get("id")
    }


def _clean_model_text(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        try:
            parsed = json.loads(text)
            if isinstance(parsed, str):
                text = parsed.strip()
        except Exception:
            pass
    return text


def _messages(source: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are a Japanese newsroom translation repair engine. "
                "Translate Traditional Chinese/Cantonese news copy into natural, "
                "fact-faithful Japanese. Preserve names, numbers, dates, places, "
                "uncertainty and attribution exactly. Do not summarize, omit, add "
                "facts, explain, use markdown, or mention this instruction. "
                "Return only the repaired Japanese text."
            ),
        },
        {"role": "user", "content": source},
    ]


def _call_model(model: str, source: str) -> str:
    response = requests.post(
        API,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "model": model,
            "messages": _messages(source),
            "temperature": 0,
            "max_tokens": 1800,
        },
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("GitHub Models returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    value = message.get("content") if isinstance(message, dict) else None
    value = _clean_model_text(value)
    if not value:
        raise RuntimeError("GitHub Models returned empty translation")
    return value


def bad_translation(source: str, target: str, strict: bool, field: str) -> bool:
    if not isinstance(target, str) or not target.strip():
        return True
    if not safe.target_quality_ok(source, target, strict=strict):
        return True
    return bool(newsroom_quality.hard_reason(source, target, field))


def translate(source: str, strict: bool, field: str) -> str:
    if not TOKEN:
        raise RuntimeError("GITHUB_MODELS_TOKEN/GITHUB_TOKEN missing")
    errors = []
    for model in MODELS:
        try:
            value = newsroom_quality.deterministic_postedit(
                source,
                _call_model(model, source),
                field,
            )
            if bad_translation(source, value, strict, field):
                errors.append(f"{model}=quality-rejected")
                print(
                    "GITHUB_MODELS_TRANSLATION_REJECT",
                    f"model={model}",
                    f"field={field}",
                    f"source={source[:80]!r}",
                    f"output={value[:80]!r}",
                )
                continue
            print(
                "GITHUB_MODELS_TRANSLATION_OK",
                f"model={model}",
                f"field={field}",
                f"source={source[:80]!r}",
            )
            return value
        except Exception as exc:
            errors.append(f"{model}={type(exc).__name__}:{exc}")
            print(
                "GITHUB_MODELS_TRANSLATION_ERROR",
                f"model={model}",
                f"field={field}",
                f"error={type(exc).__name__}:{str(exc)[:240]}",
            )
    raise RuntimeError("GitHub Models translation repair exhausted: " + "; ".join(errors))


def rebuild_decorations(name: str, payload: dict) -> dict:
    if name == "latest.json":
        payload = base.add_furigana(base.attach_daily_audio(payload), "articles")
    elif name == "live.json":
        payload = base.add_furigana(base.attach_live_audio(payload), "items")
    payload["furiganaEngineVersion"] = furigana_safe_runtime.engine_name()
    payload["newsroomQualityVersion"] = 1
    return payload


def repair_file(name: str) -> int:
    path = DATA / name
    local = json.loads(path.read_text(encoding="utf-8"))
    source = snapshot.load_json(name)
    source_by_id = index_stories(source)
    local_by_id = index_stories(local)
    repaired = 0
    failures = []

    for story_id, local_story in local_by_id.items():
        source_story = source_by_id.get(story_id)
        if not source_story:
            status = str(local_story.get("translationStatus") or "").strip().upper()
            if status in BAD_STATUSES:
                failures.append(f"{name}:{story_id}:degraded-story-not-in-source")
            continue

        changed = False
        for field in CORE_FIELDS:
            source_text = source_story.get(field)
            if not isinstance(source_text, str) or not source_text.strip():
                continue
            target = str(local_story.get(field) or "")
            strict = field in integrity.PROSE_FIELDS
            polished = newsroom_quality.deterministic_postedit(source_text, target, field)
            if polished != target and not bad_translation(source_text, polished, strict, field):
                local_story[field] = polished
                target = polished
                changed = True
                repaired += 1
            if bad_translation(source_text, target, strict, field):
                local_story[field] = translate(source_text, strict, field)
                changed = True
                repaired += 1
            if bad_translation(source_text, str(local_story.get(field) or ""), strict, field):
                failures.append(f"{name}:{story_id}:{field}")

        if changed:
            local_story.pop("furigana", None)

    # Full second-pass source-linked validation before clearing any degraded bit.
    for story_id, local_story in index_stories(local).items():
        source_story = source_by_id.get(story_id)
        status = str(local_story.get("translationStatus") or "").strip().upper()
        if not source_story:
            if status in BAD_STATUSES:
                failures.append(f"{name}:{story_id}:unmatched-{status}")
            continue
        for field in CORE_FIELDS:
            source_text = source_story.get(field)
            if not isinstance(source_text, str) or not source_text.strip():
                continue
            target = str(local_story.get(field) or "")
            strict = field in integrity.PROSE_FIELDS
            if bad_translation(source_text, target, strict, field):
                failures.append(f"{name}:{story_id}:{field}:revalidation")
        if status in BAD_STATUSES:
            local_story.pop("translationStatus", None)

    if failures:
        raise RuntimeError(
            "GitHub Models recovery still has rejected fields: "
            + ", ".join(sorted(set(failures))[:40])
        )

    local["translationDegraded"] = False
    local["translationDeferredCount"] = 0
    local["translationDeferredIds"] = []
    if "translationDeferredMetadata" in local:
        local["translationDeferredMetadata"] = []
    local = rebuild_decorations(name, local)
    path.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("GITHUB_MODELS_CORE_FILE_OK", name, f"repaired_fields={repaired}")
    return repaired


def main() -> int:
    if not TOKEN:
        raise SystemExit("GITHUB_MODELS_TOKEN/GITHUB_TOKEN is required")
    if not MODELS:
        raise SystemExit("No GitHub Models translation model configured")

    newsroom_quality.install(safe)
    furigana_safe_runtime.install()

    total = 0
    for name in CORE_FILES:
        total += repair_file(name)

    print(
        "GITHUB_MODELS_CORE_RECOVERY_OK",
        f"repaired_fields={total}",
        f"snapshot={snapshot.snapshot_commit()}",
        "torch_independent=true",
        "degraded=false",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
