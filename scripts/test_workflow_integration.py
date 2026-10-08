import ast
import re
import unittest
from pathlib import Path


HERE = Path(__file__).parent


class RollingWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        workflow = HERE / "repair-all-published-quality.yml"
        if not workflow.is_file():
            workflow = HERE.parent / ".github" / "workflows" / "repair-all-published-quality.yml"
        self.source = workflow.read_text(encoding="utf-8")

    def test_single_frozen_source_and_writer_lock_remain(self):
        self.assertEqual(self.source.count("run: python scripts/cantonese_snapshot.py"), 1)
        self.assertIn("group: japanese-newsroom-writer\n  cancel-in-progress: false", self.source)

    def test_local_fallback_only_follows_failed_remote_result_or_freshness(self):
        probe = self.source.index("id: remote_freshness")
        fallback = self.source.index("name: Recover current rolling source")
        validator = self.source.index("name: Validate every rolling topic and stock layer")
        self.assertLess(probe, fallback)
        self.assertLess(fallback, validator)
        self.assertEqual(self.source.count(
            "if: steps.remote_repair.outcome == 'failure' || steps.remote_freshness.outcome == 'failure'"), 3)

    def test_publication_is_after_existing_degraded_and_freshness_gates(self):
        names = ["Validate every rolling topic and stock layer",
                 "Reject any remaining degraded rolling metadata",
                 "Require exhaustive recovery to advance current source freshness",
                 "Publish repaired rolling Japanese immediately"]
        indexes = [self.source.index("name: " + name) for name in names]
        self.assertEqual(indexes, sorted(indexes))
        self.assertIn("python scripts/validate_extra_layers.py", self.source)
        self.assertIn("ROLLING_EXHAUSTIVE_OUTCOME_NOT_ACCEPTED", self.source)

    def test_reviewed_model_dependencies_and_cache_are_unchanged(self):
        self.assertIn("torch==2.8.0", self.source)
        self.assertIn("pip install -r requirements-translation.txt", self.source)
        self.assertIn("key: hf-m2m100-418m-core-fallback-v1", self.source)
        self.assertIn("timeout-minutes: 16", self.source)
        self.assertIn("data/topic-more data/translation-cache.json", self.source)

    def test_all_embedded_python_checks_compile(self):
        programs = re.findall(r"          python - <<'PY'\n(.*?)          PY", self.source, re.S)
        self.assertEqual(len(programs), 4)
        for program in programs:
            code = "\n".join(line[10:] if line.startswith("          ") else line
                             for line in program.splitlines())
            ast.parse(code)

    def test_worker_does_not_dispatch_other_robot_or_edit_controller_state(self):
        self.assertNotIn("workflow_dispatch\n", self.source)
        implementation = (HERE / "secondary_local_rolling_recovery.py").read_text(encoding="utf-8")
        tree = ast.parse(implementation)
        calls = [node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertNotIn("urlopen", calls)
        self.assertNotIn("post", calls)
        self.assertNotIn("dispatch", calls)


if __name__ == "__main__":
    unittest.main()
