"""Exact section chrome regression tests with unchanged production quality rules.

No ML, news discovery, hosted translation, credentials, or external writes.
Reference AST loading only removes imports and entry points; quality functions
and constants execute unchanged. Works in scripts/ or the captured workspace.
"""
import ast
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from test_secondary_local_rolling import HERE, load_module


def source_path(name):
    local = HERE / name
    if local.is_file():
        return local
    reference = HERE / "references" / name
    if reference.is_file():
        return reference
    if name == "newsroom_quality.py":
        return HERE.parent / "japanese-recovery" / name
    if name == "sync_and_translate.py":
        return HERE / "references" / "base_constants.py"
    raise RuntimeError(f"Missing production quality reference: {name}")


def reference(path, namespace, selected=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.If)):
            continue
        if selected is not None:
            name = node.name if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else None
            if isinstance(node, ast.Assign):
                names = {target.id for target in node.targets if isinstance(target, ast.Name)}
                if not names & selected:
                    continue
            elif name not in selected:
                continue
        nodes.append(node)
    module = ModuleType(path.stem)
    module.__dict__.update(namespace, __file__=str(path))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), module.__dict__)
    return module


def load_with_actual_quality():
    module = load_module()
    integrity = reference(source_path("validate_content_integrity.py"),
                          {"re": re, "json": json, "Path": Path})
    constants = reference(source_path("sync_and_translate.py"), {"Path": Path},
                          {"KEEP_KEYS", "TRANSLATE_KEYS", "CACHE_VERSION", "existing_features_ok"})
    module.base.KEEP_KEYS = constants.KEEP_KEYS
    module.base.TRANSLATE_KEYS = constants.TRANSLATE_KEYS
    module.base.CACHE_VERSION = constants.CACHE_VERSION
    module.base.existing_features_ok = constants.existing_features_ok
    safe = reference(source_path("safe_sync.py"),
                     {"re": re, "os": os, "time": time, "hashlib": hashlib,
                      "base": module.base, "integrity": integrity})
    extra = reference(source_path("sync_cantonese_layers.py"),
                      {"re": re, "safe": safe},
                      {"HAN_RE", "HIRA_RE", "needs_cantonese_translation", "story_like"})
    module.base.likely_chinese_source = extra.needs_cantonese_translation
    quality = reference(source_path("newsroom_quality.py"), {"re": re})
    quality.install(safe)
    module.safe, module.integrity, module.newsroom_quality = safe, integrity, quality
    module.extra.story_like = extra.story_like
    module.TEXT_KEYS = set(constants.TRANSLATE_KEYS) | {"impactLabel", "sectionLabel"}
    return module


class StaticSubtitleTests(unittest.TestCase):
    def setUp(self):
        self.m = load_with_actual_quality()
        self.temporary = tempfile.TemporaryDirectory(dir=HERE)
        self.addCleanup(self.temporary.cleanup)
        self.m.DATA = Path(self.temporary.name)
        self.m.base.CACHE_PATH = self.m.DATA / "translation-cache.json"
        self.football_source = "全球足球賽事、球會、國家隊、轉會與監管"
        self.football_target = "世界のサッカー大会・クラブ・代表チーム・移籍・規制と監督"

    def test_all_seven_exact_metadata_labels_pass_actual_unchanged_quality(self):
        self.assertEqual(len(self.m.STATIC_SECTION_SUBTITLES), 7)
        for (slug, source), target in self.m.STATIC_SECTION_SUBTITLES.items():
            with self.subTest(slug=slug):
                self.assertIsNone(self.m.safe.source_target_quality_reason(source, target, strict=False))
                self.assertTrue(self.m.valid_field(source, target, "subtitle"))
                section = {"slug": slug, "subtitle": source, "articleIds": ["original-id"]}
                self.assertEqual(self.m.localize_static_subtitle(section, "sections"), target)
                self.assertEqual(self.m.localize_static_subtitle(section, "extraTopics"), target)

    def test_observed_bad_mt_and_old_zero_overlap_localization_remain_rejected(self):
        for target in ("グローバルサッカーのイベント、サッカー、チーム、移転と規制",
                       "グローバルサッカーイベント、サッカークラブ、国立チーム、転送および規制",
                       "世界のサッカー大会・クラブ・代表・移籍・規制"):
            with self.subTest(target=target):
                self.assertFalse(self.m.valid_field(self.football_source, target, "subtitle"))
        self.assertTrue(self.m.valid_field(self.football_source, self.football_target, "subtitle"))

    def test_real_existing_feature_gate_is_not_stubbed_or_weakened(self):
        self.assertFalse(self.m.base.existing_features_ok("latest.json", {"language": "ja", "articles": []}))
        story = {"subtitle": self.football_target}
        self.assertFalse(self.m.base.existing_features_ok("latest.json", {"language": "ja", "articles": [story]}))
        story.update(furigana={}, audio="audio/original.mp3", timing="audio/timing/original.json")
        self.assertTrue(self.m.base.existing_features_ok("latest.json", {"language": "ja", "articles": [story]}))

    def test_section_localization_keeps_structure_identity_and_source_metadata(self):
        source = {"date": "2026-10-08", "generatedAt": "2026-10-08T08:16:53+08:00",
                  "sections": [{"slug": "football", "subtitle": self.football_source,
                                "articleIds": ["same-id"], "sourceUrl": "https://source.test/f"}]}
        before = deepcopy(source)
        with patch.dict(sys.modules, {"secondary_local_core_recovery": None}):
            target = self.m.convert_tree(source)
        self.m.verify_tree(source, target)
        expected = deepcopy(source)
        expected["sections"][0]["subtitle"] = self.football_target
        self.assertEqual(target, expected)
        self.assertEqual(source, before)
        self.assertEqual(self.m.base.CACHE, {})

    def test_wrong_slug_changed_source_or_article_subtitle_cannot_use_glossary(self):
        for section, parent in (
            ({"slug": "japan", "subtitle": self.football_source}, "sections"),
            ({"slug": "football", "subtitle": self.football_source + "、2026年"}, "sections"),
            ({"slug": "football", "subtitle": self.football_source}, "articles"),
            ({"slug": "football", "subtitle": self.football_source,
              "id": "news", "title": "記事", "body": "記事本文"}, "sections"),
        ):
            with self.subTest(parent=parent, section=section):
                self.assertIsNone(self.m.localize_static_subtitle(section, parent))

    def test_unrecognized_and_story_copy_keep_normal_model_path_and_fail_closed(self):
        source = {"articles": [{"id": "news", "slug": "football", "subtitle": self.football_source}]}
        with patch.dict(sys.modules, {"secondary_local_core_recovery": None}):
            with self.assertRaises(ModuleNotFoundError):
                self.m.convert_tree(source)
        self.assertEqual(self.m.base.CACHE, {})

    def test_glossary_does_not_bypass_a_later_quality_rejection(self):
        section = {"slug": "football", "subtitle": self.football_source}
        with patch.object(self.m.safe, "target_quality_ok", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "unchanged source-aware quality gate"):
                self.m.localize_static_subtitle(section, "sections")
        self.assertEqual(self.m.base.CACHE, {})


if __name__ == "__main__":
    unittest.main()
