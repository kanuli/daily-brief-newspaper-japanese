#!/usr/bin/env python3
"""Independent secondary local M2M100 recovery for degraded Daily/Live fields.

This is the final Core translation fallback. It is deliberately independent of
Google/GTX/MyMemory and independent of the primary OPUS-MT model. Traditional
Chinese is normalized locally with OpenCC, then translated locally with M2M100.
Only source-linked fields that still fail newsroom quality gates are replaced.
No degraded marker is cleared until a full second-pass validation succeeds.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import torch
from opencc import OpenCC
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

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

# Keep the final fallback deterministic across queued/older workflow runs.
# Do not let stale workflow environment variables switch this backend.
MODEL_NAME = "facebook/m2m100_418M"
SOURCE_LANG = "zh"
TARGET_LANG = "ja"
MAX_SOURCE_TOKENS = 480
MAX_NEW_TOKENS = 520
_MODEL = None
_TOKENIZER = None
_LOAD_LOCK = threading.Lock()
_T2S = OpenCC("t2s")


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


def load_model():
    global _MODEL, _TOKENIZER
    if _MODEL is not None and _TOKENIZER is not None:
        return _TOKENIZER, _MODEL
    with _LOAD_LOCK:
        if _MODEL is None or _TOKENIZER is None:
            threads = max(1, min(4, os.cpu_count() or 2))
            torch.set_num_threads(threads)
            _TOKENIZER = AutoTokenizer.from_pretrained(MODEL_NAME)
            _TOKENIZER.src_lang = SOURCE_LANG
            _MODEL = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
            _MODEL.to("cpu")
            _MODEL.eval()
            print(
                "SECONDARY_LOCAL_MODEL_READY",
                f"model={MODEL_NAME}",
                f"source_lang={SOURCE_LANG}",
                f"target_lang={TARGET_LANG}",
                f"cpu_threads={threads}",
            )
    return _TOKENIZER, _MODEL


def model_translate(text: str, source_lang: str, target_lang: str, *, beams: int = 4) -> str:
    tokenizer, model = load_model()
    source = str(text or "")
    if source_lang == "zh":
        source = _T2S.convert(source)
    tokenizer.src_lang = source_lang
    encoded = tokenizer(
        source,
        return_tensors="pt",
        truncation=False,
    )
    if encoded["input_ids"].shape[-1] > MAX_SOURCE_TOKENS:
        raise RuntimeError("M2M100 source exceeds token budget; refusing silent truncation")
    if not hasattr(tokenizer, "get_lang_id"):
        raise RuntimeError("M2M100 tokenizer does not expose get_lang_id")
    target_id = tokenizer.get_lang_id(target_lang)
    with torch.inference_mode():
        generated = model.generate(
            **encoded,
            forced_bos_token_id=target_id,
            max_new_tokens=MAX_NEW_TOKENS,
            num_beams=max(1, int(beams)),
            no_repeat_ngram_size=4,
            early_stopping=True,
            renormalize_logits=True,
        )
    value = tokenizer.batch_decode(generated, skip_special_tokens=True)[0].strip()
    if not value:
        raise RuntimeError(
            f"M2M100 returned empty translation source={source_lang} target={target_lang}"
        )
    return value


def translate_chunk(text: str, strict: bool, field: str) -> str:
    direct = model_translate(text, SOURCE_LANG, TARGET_LANG, beams=5)
    direct = newsroom_quality.deterministic_postedit(text, direct, field)
    if not bad_translation(text, direct, strict, field):
        return direct

    print(
        "SECONDARY_LOCAL_DIRECT_REJECT",
        f"field={field}",
        f"source={text[:100]!r}",
        f"output={direct[:100]!r}",
    )

    # Independent decoding path using the same fully-local model. Chinese->English
    # and English->Japanese often resolves a malformed direct zh->ja decode without
    # touching any hosted translation provider.
    english = model_translate(text, SOURCE_LANG, "en", beams=5)
    pivot = model_translate(english, "en", TARGET_LANG, beams=5)
    pivot = newsroom_quality.deterministic_postedit(text, pivot, field)
    if not bad_translation(text, pivot, strict, field):
        print(
            "SECONDARY_LOCAL_PIVOT_OK",
            f"field={field}",
            f"source={text[:100]!r}",
        )
        return pivot

    print(
        "SECONDARY_LOCAL_PIVOT_REJECT",
        f"field={field}",
        f"source={text[:100]!r}",
        f"english={english[:100]!r}",
        f"output={pivot[:100]!r}",
    )

    # Preserve sentence context before splitting at commas. Short subordinate
    # clauses lose referents and can fail even when the complete sentence has
    # an acceptable direct or pivot translation. Every sentence and the final
    # assembled field must still pass the existing source-linked quality gates.
    sentences = [
        part for part in re.split(r"(?<=[。！？!?])|\n\s*\n", str(text or ""))
        if part and part.strip()
    ]
    if len(sentences) > 1:
        resolved = []
        for index, sentence in enumerate(sentences, 1):
            candidate = model_translate(sentence, SOURCE_LANG, TARGET_LANG, beams=6)
            candidate = newsroom_quality.deterministic_postedit(sentence, candidate, field)
            if bad_translation(sentence, candidate, strict, field):
                en_sentence = model_translate(sentence, SOURCE_LANG, "en", beams=6)
                candidate = model_translate(en_sentence, "en", TARGET_LANG, beams=6)
                candidate = newsroom_quality.deterministic_postedit(sentence, candidate, field)
            if bad_translation(sentence, candidate, strict, field):
                print(
                    "SECONDARY_LOCAL_SENTENCE_REJECT",
                    f"field={field}",
                    f"sentence={index}/{len(sentences)}",
                    f"source={sentence!r}",
                    f"output={candidate!r}",
                    f"reason={quality_reason(sentence, candidate, strict, field)}",
                )
                break
            resolved.append(candidate)
        else:
            combined = "".join(resolved)
            combined = newsroom_quality.deterministic_postedit(text, combined, field)
            if not bad_translation(text, combined, strict, field):
                print("SECONDARY_LOCAL_SENTENCE_RETRY_OK", f"field={field}",
                      f"sentences={len(sentences)}")
                return combined

    # Final local-only retry: translate clauses independently, choosing direct
    # or pivot per clause, then re-run the authoritative whole-field quality gate.
    clauses = [
        part for part in re.split(r"(?<=[，,；;：:。！？!?])", str(text or ""))
        if part and part.strip()
    ]
    if len(clauses) > 1:
        resolved = []
        for index, clause in enumerate(clauses, 1):
            candidate = model_translate(clause, SOURCE_LANG, TARGET_LANG, beams=6)
            candidate = newsroom_quality.deterministic_postedit(clause, candidate, field)
            if bad_translation(clause, candidate, False, field):
                en_clause = model_translate(clause, SOURCE_LANG, "en", beams=6)
                candidate = model_translate(en_clause, "en", TARGET_LANG, beams=6)
                candidate = newsroom_quality.deterministic_postedit(clause, candidate, field)
            if bad_translation(clause, candidate, False, field):
                raise RuntimeError(
                    f"clause {index}/{len(clauses)} failed direct and pivot quality; "
                    f"field={field}; source={clause!r}; output={candidate!r}; "
                    f"reason={quality_reason(clause, candidate, False, field)}"
                )
            resolved.append(candidate)
        combined = "".join(resolved)
        combined = newsroom_quality.deterministic_postedit(text, combined, field)
        if not bad_translation(text, combined, strict, field):
            print(
                "SECONDARY_LOCAL_CLAUSE_RETRY_OK",
                f"field={field}",
                f"clauses={len(clauses)}",
            )
            return combined

    raise RuntimeError("direct, pivot and clause-local M2M100 paths all failed quality")


def bad_translation(source: str, target: str, strict: bool, field: str) -> bool:
    if not isinstance(target, str) or not target.strip():
        return True
    if not safe.target_quality_ok(source, target, strict=strict):
        return True
    return bool(newsroom_quality.hard_reason(source, target, field))


def quality_reason(source: str, target: str, strict: bool, field: str) -> str:
    return (
        safe.source_target_quality_reason(source, target, strict=strict)
        or newsroom_quality.hard_reason(source, target, field)
        or "target_quality_ok rejected output"
    )


def translate(source: str, strict: bool, field: str) -> str:
    errors = []
    pieces = base.chunks(source, limit=280) or [source]
    translated = []
    for index, piece in enumerate(pieces, 1):
        try:
            value = translate_chunk(piece, strict, field)
            translated.append(value)
            print(
                "SECONDARY_LOCAL_CHUNK_OK",
                f"field={field}",
                f"part={index}/{len(pieces)}",
                f"source={piece[:70]!r}",
            )
        except Exception as exc:
            errors.append(f"part={index}:{type(exc).__name__}:{exc}")
            raise RuntimeError(
                "Secondary local M2M100 translation failed: " + "; ".join(errors)
            ) from exc

    value = "".join(translated)
    value = newsroom_quality.deterministic_postedit(source, value, field)
    if bad_translation(source, value, strict, field):
        raise RuntimeError(
            f"Secondary local M2M100 result rejected after reassembly: field={field}"
        )
    return value


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

        if changed:
            local_story.pop("furigana", None)

    # Second-pass source-linked validation before any degraded marker can clear.
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
            "Secondary local recovery still has rejected fields: "
            + ", ".join(sorted(set(failures))[:40])
        )

    local["translationDegraded"] = False
    local["translationDeferredCount"] = 0
    local["translationDeferredIds"] = []
    if "translationDeferredMetadata" in local:
        local["translationDeferredMetadata"] = []
    local = rebuild_decorations(name, local)
    path.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SECONDARY_LOCAL_CORE_FILE_OK", name, f"repaired_fields={repaired}")
    return repaired


def main() -> int:
    newsroom_quality.install(safe)
    furigana_safe_runtime.install()
    total = 0
    for name in CORE_FILES:
        total += repair_file(name)
    print(
        "SECONDARY_LOCAL_CORE_RECOVERY_OK",
        f"repaired_fields={total}",
        f"snapshot={snapshot.snapshot_commit()}",
        f"model={MODEL_NAME}",
        "remote_translation_api=false",
        "degraded=false",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


