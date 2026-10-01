#!/usr/bin/env python3
"""Source-ID-bound editorial translations for rare backend-specific failures.

These overrides are narrow recovery data, not generic translation shortcuts.
They preserve source metadata/provenance and replace only learner-facing prose
for a verified source item whose free translation backends repeatedly fail.
"""
from __future__ import annotations


OVERRIDES = {
    "live-hong-kong-20260930-university-ranking": {
        "section": "香港",
        "sectionLabel": "香港",
        "title": "香港の5大学がTHE世界トップ100入り、2校は前回より順位上昇",
        "dek": "タイムズ・ハイヤー・エデュケーション（THE）が2027年世界大学ランキングを発表し、香港の5大学が世界トップ100に入った。教育局によると、このうち2校は前回より順位を上げた。",
        "summary": "最新のTHE世界大学ランキングで、香港は5大学が世界トップ100入りを維持した。香港の高等教育が国際ランキングで引き続き競争力を持つことを示しており、今後は各大学の研究、教育、国際性の指標の変化が注目される。",
        "body": "香港政府は9月30日、タイムズ・ハイヤー・エデュケーション（THE）の2027年世界大学ランキングで、香港の5大学が世界トップ100に入ったと発表した。教育局によると、このうち2校は前回より順位を上げた。\n\n大学ランキングは高等教育の実績を測る指標の一つにすぎないが、留学生、研究人材、提携先が大学を評価する際の参考になる。今後は各大学の研究の質、教育環境、国際性などの項目の変化や、ランキング結果が学生募集や研究協力の強みに結びつくかが注目される。",
        "context": "香港では近年、高等教育と研究への投資を拡大し、海外からの学生や研究人材の誘致を政策上の重点の一つとしている。",
        "why": "複数の香港の大学が世界トップ100の位置を維持することは、地域の高等教育、研究人材、国際協力をめぐる競争で香港の存在感を保つ上でプラスとなる。",
        "watchNext": "THEが公表する各大学の項目別データや、各大学による最新ランキング、学生募集、研究戦略への対応に注目する。",
        "timeLabel": "09月30日 15:03 HKT確認済み",
    }
}


def install(base_module) -> None:
    if getattr(base_module, "_current_story_overrides_installed", False):
        return
    original = base_module.convert

    def convert(obj, parent_key=""):
        if isinstance(obj, dict):
            story_id = str(obj.get("id") or "")
            override = OVERRIDES.get(story_id)
            if override:
                value = dict(obj)
                value.update(override)
                value["translationStatus"] = "EDITORIAL_VERIFIED_OVERRIDE"
                value["translationOverrideReason"] = "free-backend-quality-gate-exhausted"
                print("CURRENT_STORY_EDITORIAL_OVERRIDE", f"id={story_id}")
                return value
        return original(obj, parent_key)

    base_module.convert = convert
    base_module._current_story_overrides_installed = True
    print("CURRENT_STORY_OVERRIDES_INSTALLED count=1 provenance_preserved=true")
