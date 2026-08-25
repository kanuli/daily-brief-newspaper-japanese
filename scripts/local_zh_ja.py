#!/usr/bin/env python3
"""Local Chinese/Cantonese -> Japanese neural translation.

Production translation deliberately avoids Google/remote translation APIs.
The model is Helsinki-NLP/opus-mt-tc-big-zh-ja (OPUS-MT, CC-BY-4.0), loaded
locally on the GitHub Actions runner and reused for small batched inference.
Traditional Chinese is preserved for the first pass; failed items can be
retried after local Traditional -> Simplified normalization with OpenCC.
"""
from __future__ import annotations

import os
import threading
from typing import Iterable

import torch
from opencc import OpenCC
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

MODEL_NAME = "Helsinki-NLP/opus-mt-tc-big-zh-ja"
MODEL_BATCH_SIZE = 4
MAX_SOURCE_TOKENS = 480
MAX_TARGET_TOKENS = 512

_MODEL = None
_TOKENIZER = None
_LOAD_LOCK = threading.Lock()
_INFER_LOCK = threading.Lock()
_T2S = OpenCC("t2s")


def simplify_traditional(text: str) -> str:
    """Normalize Traditional Chinese locally; never touches a remote service."""
    return _T2S.convert(str(text or ""))


def _load():
    global _MODEL, _TOKENIZER
    if _MODEL is not None and _TOKENIZER is not None:
        return _TOKENIZER, _MODEL
    with _LOAD_LOCK:
        if _MODEL is None or _TOKENIZER is None:
            threads = max(1, min(4, os.cpu_count() or 2))
            torch.set_num_threads(threads)
            _TOKENIZER = AutoTokenizer.from_pretrained(MODEL_NAME)
            _MODEL = AutoModelForSeq2SeqLM.from_pretrained(
                MODEL_NAME,
                use_safetensors=True,
            )
            _MODEL.to("cpu")
            _MODEL.eval()
            print(f"LOCAL_MT_MODEL_READY model={MODEL_NAME} cpu_threads={threads}")
    return _TOKENIZER, _MODEL


def _batched(values: list[str], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def translate_many(
    texts: Iterable[str],
    batch_size: int = MODEL_BATCH_SIZE,
    *,
    normalize_traditional: bool = False,
    num_beams: int = 4,
) -> list[str]:
    """Translate locally while preserving order and using one model instance."""
    values = [str(x or "") for x in texts]
    if normalize_traditional:
        values = [simplify_traditional(x) for x in values]
    if not values:
        return []

    tokenizer, model = _load()
    output: list[str] = []
    with _INFER_LOCK, torch.inference_mode():
        for batch in _batched(values, max(1, int(batch_size))):
            encoded = tokenizer(
                batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=MAX_SOURCE_TOKENS,
            )
            generated = model.generate(
                **encoded,
                max_length=MAX_TARGET_TOKENS,
                num_beams=max(1, int(num_beams)),
                early_stopping=True,
                renormalize_logits=True,
            )
            decoded = tokenizer.batch_decode(generated, skip_special_tokens=True)
            output.extend(str(x or "").strip() for x in decoded)
    return output


def translate_one(
    text: str,
    *,
    normalize_traditional: bool = False,
    num_beams: int = 4,
) -> str:
    values = translate_many(
        [text],
        batch_size=1,
        normalize_traditional=normalize_traditional,
        num_beams=num_beams,
    )
    return values[0] if values else ""


if __name__ == "__main__":
    sample = "香港今日天氣炎熱，市民外出時要注意補充水分。"
    print(translate_one(sample))
