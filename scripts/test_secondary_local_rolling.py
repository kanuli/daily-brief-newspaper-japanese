import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


HERE = Path(__file__).parent


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def story_like(value):
    return isinstance(value, dict) and value.get("id") and value.get("title") and value.get("body")


def fake_module(name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    return module


def load_module():
    """Control tests use no hosted API or ML download; quality is injected."""
    modules = {
        "cantonese_snapshot": fake_module("cantonese_snapshot"),
        "fast_safe_sync": fake_module("fast_safe_sync", localize_non_chinese=lambda s: s),
        "furigana_safe_runtime": fake_module("furigana_safe_runtime", engine_name=lambda: "test"),
        "newsroom_quality": fake_module("newsroom_quality", hard_reason=lambda *a: None,
                                        deterministic_postedit=lambda s, t, f: t),
        "run_extra_sync_editor": fake_module("run_extra_sync_editor", _prepare_source=lambda n, s: deepcopy(s)),
        "safe_sync": fake_module("safe_sync", STRICT_PROSE_KEYS={"body", "summary"},
                                 target_quality_ok=lambda s, t, strict=False: bool(t) and t != "BAD",
                                 bad_error_text=lambda s: "ERROR" in s),
        "sync_and_translate": fake_module("sync_and_translate", CACHE_VERSION="test", CACHE={},
                                           KEEP_KEYS={"id", "sourceUrl", "updatedAt", "date"},
                                           TRANSLATE_KEYS={"title", "summary", "body", "timeLabel"}),
        "sync_cantonese_layers": fake_module("sync_cantonese_layers", SCHEMA="test-schema",
                                             fingerprint=fingerprint, story_like=story_like,
                                             decorate_story_tree=lambda t, group: t),
        "validate_content_integrity": fake_module("validate_content_integrity",
                                                    STORY_TEXT_FIELDS={"title", "summary", "body"},
                                                    PROSE_FIELDS={"body", "summary"}),
    }
    spec = importlib.util.spec_from_file_location("rolling_recovery", HERE / "secondary_local_rolling_recovery.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class LocalRollingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.m = load_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.m.DATA = Path(self.temporary.name)
        self.m.base.CACHE_PATH = self.m.DATA / "translation-cache.json"
        self.source = {"date": "2026-10-08", "generatedAt": "2026-10-08T05:11:48Z",
                       "stories": [{"id": "a", "title": "原文", "body": "本文",
                                    "summary": "摘要", "sourceUrl": "https://source.test/a",
                                    "eventPublishedAt": "2026-09-25T04:00:00Z"}]}
        self.japanese = deepcopy(self.source)
        self.japanese["stories"][0].update(title="題名", body="本文です。", summary="概要です。")
        self.japanese.update(language="ja", sourceFile="live.json", translationDegraded=False,
                             translationDeferredCount=0, translationSource=self.m.SOURCE_REPOSITORY,
                             sourceFingerprint=fingerprint(self.source))

    def test_current_core_reuses_only_source_bound_fields(self):
        count = self.m.seed_core_file("live.json", self.source, self.japanese)
        self.assertEqual(count, 3)
        self.assertEqual(self.m.base.CACHE[self.m.cache_key("本文")], "本文です。")

    def test_same_id_with_changed_source_does_not_seed(self):
        current = deepcopy(self.source)
        current["stories"][0]["body"] += "追記"
        self.assertEqual(self.m.seed_core_file("live.json", current, self.japanese), 0)
        self.assertEqual(self.m.base.CACHE, {})

    def test_url_identity_and_degraded_state_are_required(self):
        for mutation in (lambda p: p.update(translationDegraded=True),
                         lambda p: p.update(translationDeferredCount=1),
                         lambda p: p["stories"][0].update(sourceUrl="https://other.test/a"),
                         lambda p: p["stories"][0].update(translationStatus="TRANSLATION_DEGRADED")):
            target = deepcopy(self.japanese)
            mutation(target)
            self.assertEqual(self.m.seed_core_file("live.json", self.source, target), 0)
        self.assertEqual(self.m.base.CACHE, {})

    def test_generic_availability_copy_is_not_cached_even_if_gate_passes(self):
        self.japanese["stories"][0]["summary"] = "詳細な日本語本文は自動復旧処理で更新します。"
        self.assertEqual(self.m.seed_core_file("live.json", self.source, self.japanese), 2)
        self.assertNotIn(self.m.cache_key("摘要"), self.m.base.CACHE)

    def test_core_seed_individual_quality_still_authoritative(self):
        self.japanese["stories"][0]["body"] = "BAD"
        self.assertEqual(self.m.seed_core_file("live.json", self.source, self.japanese), 2)
        self.assertNotIn(self.m.cache_key("本文"), self.m.base.CACHE)

    def test_cached_layer_never_loads_or_calls_a_translation_provider(self):
        self.m.seed_core_file("live.json", self.source, self.japanese)
        with patch.dict(sys.modules, {"secondary_local_core_recovery": None}):
            self.assertEqual(self.m.recover_file("desk-latest.json", self.source), 1)
        result = json.loads((self.m.DATA / "desk-latest.json").read_text(encoding="utf-8"))
        self.assertEqual(result["generatedAt"], self.source["generatedAt"])
        self.assertEqual(result["stories"][0]["eventPublishedAt"], "2026-09-25T04:00:00Z")
        self.assertEqual(result["stories"][0]["id"], "a")
        self.assertFalse(result["translationDegraded"])

    def test_unseeded_field_uses_local_secondary_with_concrete_strict_field(self):
        calls = []
        def translate(source, strict, field):
            calls.append((source, strict, field))
            return "正常な本文です。"
        backend = fake_module("secondary_local_core_recovery", translate=translate)
        with patch.dict(sys.modules, {"secondary_local_core_recovery": backend}):
            self.assertEqual(self.m.translate_field("原文", "body"), "正常な本文です。")
        self.assertEqual(calls, [("原文", True, "body")])
        self.assertEqual(self.m.base.CACHE[self.m.cache_key("原文")], "正常な本文です。")

    def test_non_chinese_label_does_not_get_sent_to_zh_model(self):
        with patch.dict(sys.modules, {"secondary_local_core_recovery": None}):
            self.assertEqual(self.m.translate_field("US-CHINA TECH", "impactLabel"), "US-CHINA TECH")

    def test_calendar_metadata_preserves_original_date_and_time_without_mt(self):
        with patch.dict(sys.modules, {"secondary_local_core_recovery": None}):
            self.assertEqual(self.m.translate_field("2026年10月8日 18:45 HKT", "lastUpdatedLabel"),
                             "2026年10月8日 18:45 HKT")
            self.assertEqual(self.m.translate_field("2026年9月25日", "timeLabel"), "2026年9月25日")

    def test_final_quality_rejection_never_replaces_old_layer(self):
        path = self.m.DATA / "desk-latest.json"
        self.m.atomic_json(path, {"old": "still-valid"})
        before = path.read_bytes()
        backend = fake_module("secondary_local_core_recovery", translate=lambda *args: "BAD")
        with patch.dict(sys.modules, {"secondary_local_core_recovery": backend}):
            with self.assertRaisesRegex(RuntimeError, "rejected final"):
                self.m.recover_file("desk-latest.json", self.source)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn(self.m.cache_key("原文"), self.m.base.CACHE)

    def test_structure_identity_and_time_verification_fail_closed(self):
        for mutate in (lambda p: p["stories"][0].update(id="b"),
                       lambda p: p.update(generatedAt="2026-10-09T00:00:00Z"),
                       lambda p: p["stories"][0].update(eventPublishedAt="2026-10-08T05:00:00Z"),
                       lambda p: p.update(stories=[])):
            target = deepcopy(self.source)
            mutate(target)
            with self.assertRaises(RuntimeError):
                self.m.verify_tree(self.source, target)

    def test_failed_atomic_replace_preserves_old_file_and_removes_temporary(self):
        path = self.m.DATA / "stock.json"
        self.m.atomic_json(path, {"old": True})
        before = path.read_bytes()
        with patch.object(self.m.os, "replace", side_effect=OSError("simulated disk error")):
            with self.assertRaises(OSError):
                self.m.atomic_json(path, {"new": True})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.m.DATA.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
