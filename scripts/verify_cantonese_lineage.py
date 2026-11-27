"""Focused regression of the existing Cantonese-fed Japanese publishing gate."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cantonese_lineage as gate
import cantonese_snapshot as snapshot

NOW=datetime(2026,11,27,12,tzinfo=timezone.utc)
HEAD="a"*40
OTHER="b"*40


def quality(old,new,field):
    return new=="翻訳："+old


def article(identifier="a",title="測試"):
    return {"id":identifier,"title":title,"sourceUrl":"https://news.rthk.hk/example",
            "publishedAt":"2026-11-27T05:00:00Z","verifiedAt":"2026-11-27T05:05:00Z","desk":"world"}


def edition(*rows):
    return {"date":"2026-11-27","items":list(rows)}


def translate(source):
    out=deepcopy(source)
    out.update(translationSource=snapshot.REPO,sourceFingerprint=snapshot.sha(gate.canonical(source)))
    for original,item in zip(source["items"],out["items"]):
        item.update(title="翻訳："+original["title"],sourceItemFingerprint=snapshot.sha(gate.canonical(original)))
    return out


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.source=edition(article())
        self.target=translate(self.source)

    def verify(self, doc=None):
        return gate.lineage("live.json",gate.canonical(self.source),gate.canonical(doc or self.target),quality=quality)

    def test_new_and_changed_article(self):
        self.assertEqual(self.verify()[0]["id"],"a")
        current=gate.canonical(self.target)
        self.source=edition(article(),article("b","另一則"))
        self.assertEqual(len(self.verify(translate(self.source))),2)
        self.source["items"][0]["title"]="更正"
        with self.assertRaises(ValueError):
            self.verify(json.loads(current))
        self.assertEqual(self.verify(translate(self.source))[0]["id"],"a")

    def test_duplicate_substitution_category_or_quality(self):
        for patch_row in ({"id":"jiji-alone"},{"desk":"japan"},{"publishedAt":"2026-11-27T01:00:00Z"},
                          {"sourceUrl":"https://www.jiji.com/another"},{"title":"未通過審核"}):
            out=deepcopy(self.target)
            out["items"][0].update(patch_row)
            with self.assertRaises(ValueError):
                self.verify(out)
        duplicate=deepcopy(self.target)
        duplicate["items"]*=2
        with self.assertRaises(ValueError):
            self.verify(duplicate)

    def test_missing_and_stale_worker_input_proof(self):
        # The document-level fingerprint cannot replace evidence emitted by the worker.
        item = self.target["items"][0]
        saved = item.pop("sourceItemFingerprint")
        with self.assertRaisesRegex(ValueError,"translation input proof"):
            self.verify()
        item["sourceItemFingerprint"] = "0"*64
        with self.assertRaisesRegex(ValueError,"translation input proof"):
            self.verify()
        item["sourceItemFingerprint"] = saved
        self.assertEqual(self.verify()[0]["cantoneseArticleSha256"],saved)

    def test_restart_stale_gate_and_publication_scope(self):
        cwd=Path.cwd()
        with TemporaryDirectory() as tmp,patch.dict(os.environ,{"CANTONESE_SNAPSHOT_DIR":".canto/data"}):
            os.chdir(tmp)
            try:
                raw=gate.canonical(self.source)
                def upstream(revision,name,optional=False):
                    if name.startswith("topic"):
                        return None
                    return raw if name=="live.json" else b"{}"
                with patch.object(snapshot,"read_remote",side_effect=upstream),patch.object(snapshot,"resolve_commit",return_value=HEAD):
                    snapshot.capture()
                    snapshot.write_atomic(Path("data/live.json"),gate.canonical(self.target))
                    gate.seal("live.json",quality=quality,require_today=True,clock=lambda:NOW)
                    first=(Path(gate.MANIFEST)/"live.json").read_bytes()
                    # Commit movements without a new edition are idempotent.
                    with patch.object(snapshot,"resolve_commit",return_value=OTHER):
                        snapshot.capture()
                        gate.seal("live.json",quality=quality,require_today=True,clock=lambda:NOW)
                        self.assertEqual((Path(gate.MANIFEST)/"live.json").read_bytes(),first)
                    with patch.object(gate,"datetime") as clock:
                        clock.now.return_value=NOW
                        gate.prepush(["live.json"])
                        with patch.object(snapshot,"read_remote",return_value=b"{}"):
                            with self.assertRaises(ValueError):
                                gate.prepush(["live.json"])
                    with self.assertRaises(ValueError):
                        gate.seal("live.json",quality=quality,require_today=True,clock=lambda:NOW.replace(day=28))
                    # A partially overwritten snapshot is detected; capturing
                    # again is safe and does not remove the previous output.
                    snapshot.write_atomic(snapshot.snapshot_dir()/"live.json",b"{}")
                    with self.assertRaises(ValueError):
                        snapshot.load_bytes("live.json")
                    snapshot.capture()
                    self.assertEqual(snapshot.load_bytes("live.json"),raw)
            finally:
                os.chdir(cwd)


if __name__=="__main__":
    unittest.main()
