#!/usr/bin/env python3
"""Deterministic publication-chrome overrides for current-news recovery.

Section names/descriptions are fixed site navigation, not news prose. Sending
those strings to rate-limited translation services can abort an otherwise good
Daily/Live update. The wrapper is installed both at the base entry point and,
when supplied, on safe_sync.safe_convert itself so nested section dictionaries
also bypass network translation.
"""
from __future__ import annotations

SECTION_SUBTITLES = {
    "world": "アジア以外の国際政治・社会・外交・安全保障・気候・公共問題",
    "asia": "東アジア・東南アジア・南アジア・中央アジア・西アジア／中東",
    "hong-kong": "香港の公共問題・社会・暮らし・都市開発",
    "japan": "日本の政治・社会・経済・公共安全・暮らし",
    "market-economy": "世界市場・マクロ経済・企業・産業",
    "finance": "世界市場・マクロ経済・企業・産業",
    "ai-tech": "人工知能・半導体・プラットフォーム・研究・テクノロジー産業",
    "manchester-united": "マンチェスター・ユナイテッドのクラブ・試合・選手・経営",
    "football": "世界のサッカー大会・クラブ・代表・移籍・規制",
}


def _wrap(original, base):
    def convert(obj, parent_key=""):
        if isinstance(obj, dict):
            slug = str(obj.get("slug") or "")
            if slug in base.DESK_NAMES and slug in SECTION_SUBTITLES:
                source = dict(obj)
                source.pop("title", None)
                source.pop("label", None)
                source.pop("subtitle", None)
                out = original(source, parent_key)
                out["title"] = base.DESK_NAMES[slug]
                out["label"] = base.DESK_NAMES[slug]
                out["subtitle"] = SECTION_SUBTITLES[slug]
                return out
        return original(obj, parent_key)

    return convert


def install(base, safe_module=None) -> None:
    if not getattr(base, "_current_sync_overrides_installed", False):
        base.convert = _wrap(base.convert, base)
        base._current_sync_overrides_installed = True

    if safe_module is not None and not getattr(safe_module, "_current_sync_overrides_installed", False):
        # safe_convert recursively calls its module-global safe_convert symbol.
        # Rebinding that symbol therefore covers nested section dictionaries too.
        safe_module.safe_convert = _wrap(safe_module.safe_convert, base)
        safe_module._current_sync_overrides_installed = True

    print(
        "CURRENT_SYNC_OVERRIDES_INSTALLED",
        "deterministic_sections=true",
        f"safe_recursive={safe_module is not None}",
    )
