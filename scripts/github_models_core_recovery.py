#!/usr/bin/env python3
"""Targeted GitHub Models fallback for quarantined current-news fields.

This is deliberately NOT the bulk translator. The normal local OPUS-MT path,
the remote emergency path, and the bounded alternate path run first. Only fields
that still fail the existing Japanese quality gates reach this backend.

The result is always re-validated by the existing structural, semantic,
editorial, source-parity and furigana gates before publication.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

import local_translation_runtime as runtime
import repair_garbled_core as repair
import safe_sync as safe
import sync_and_translate as base


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
            "X-GitHub-Api-Version": "2026-03-10",
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


def github_models_translate(source: str, strict: bool = False) -> str:
    if not TOKEN:
        raise RuntimeError("GITHUB_MODELS_TOKEN/GITHUB_TOKEN missing")
    errors: list[str] = []
    for model in MODELS:
        try:
            value = _call_model(model, source)
            if not safe.target_quality_ok(source, value, strict=strict):
                errors.append(f"{model}=quality-rejected")
                print(
                    "GITHUB_MODELS_TRANSLATION_REJECT",
                    f"model={model}",
                    f"source={source[:80]!r}",
                    f"output={value[:80]!r}",
                )
                continue
            base.CACHE[runtime.cache_key(source)] = value
            runtime.checkpoint_cache(f"github-models-{model.replace('/', '-')}")
            print(
                "GITHUB_MODELS_TRANSLATION_OK",
                f"model={model}",
                f"source={source[:80]!r}",
            )
            return value
        except Exception as exc:
            errors.append(f"{model}={type(exc).__name__}:{exc}")
            print(
                "GITHUB_MODELS_TRANSLATION_ERROR",
                f"model={model}",
                f"error={type(exc).__name__}:{str(exc)[:240]}",
            )
    raise RuntimeError("GitHub Models translation repair exhausted: " + "; ".join(errors))


BAD_STATUSES = {"EDITORIAL_MINIMUM_FALLBACK", "TRANSLATION_FAILED", "TRANSLATION_DEGRADED"}


def _finalize_clean_metadata() -> None:
    """Clear degraded markers only after every source-linked field revalidates."""
    for name in repair.CORE_FILES:
        path = repair.DATA / name
        data = json.loads(path.read_text(encoding="utf-8"))
        source = repair.snapshot.load_json(name)
        source_by_id = repair.index_stories(source)
        local_by_id = repair.index_stories(data)
        failures: list[str] = []

        for story_id, local_story in local_by_id.items():
            source_story = source_by_id.get(story_id)
            if not source_story:
                continue
            for field in repair.CORE_FIELDS:
                source_text = source_story.get(field)
                if not isinstance(source_text, str) or not source_text.strip():
                    continue
                target = local_story.get(field)
                strict = field in repair.integrity.PROSE_FIELDS
                if repair.bad_translation(source_text, str(target or ""), strict, field):
                    failures.append(f"{name}:{story_id}:{field}")
            status = str(local_story.get("translationStatus") or "").strip().upper()
            if status in BAD_STATUSES:
                local_story.pop("translationStatus", None)

        if failures:
            raise RuntimeError(
                "GitHub Models recovery still has rejected fields: "
                + ", ".join(failures[:30])
            )

        data["translationDegraded"] = False
        data["translationDeferredCount"] = 0
        data["translationDeferredIds"] = []
        if "translationDeferredMetadata" in data:
            data["translationDeferredMetadata"] = []
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("GITHUB_MODELS_DEGRADED_MARKERS_CLEARED", name)


def main() -> int:
    if not TOKEN:
        raise SystemExit("GITHUB_MODELS_TOKEN/GITHUB_TOKEN is required")
    if not MODELS:
        raise SystemExit("No GitHub Models translation model configured")

    # Replace only the last-resort remote-quality repair hook. Bulk work remains
    # on the existing local translator and all publication gates stay unchanged.
    runtime._remote_quality_fallback = github_models_translate
    repair.main()
    _finalize_clean_metadata()
    runtime.checkpoint_cache("github-models-core-final")
    print("GITHUB_MODELS_CORE_RECOVERY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
