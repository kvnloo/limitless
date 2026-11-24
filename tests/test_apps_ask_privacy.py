"""The app names in the app-lists ask are the person's own data: only in the brief text sent to the person. Never
in the pre_llm_call state card (raw opt-in or not), the catch-up hook, a doctor reason, a tier-audit log row, a
T1 label or apps-ask.json. Synthetic phone DBs with well-known public app ids only.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import apps_ask, card, catchup, doctor, jobs_runner, tier_audit  # noqa: E402
from test_apps_ask import NAMES, NOW, aw_rows  # noqa: E402

D = 86400.0


class Private(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        aw_rows(self.st)
        self.cfg = {"state": str(self.st), "aw_db": "aw.db"}
        p = self.dir / "config.json"
        p.write_text(json.dumps(self.cfg))
        self.audit = self.dir / "audit.jsonl"
        self.env = {"LIMITLESS_CONFIG": str(p), "LIMITLESS_STATE": str(self.st), "LIMITLESS_AUDIT": str(self.audit)}
        patch = mock.patch.dict(os.environ, self.env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def assertNoName(self, blob, where):
        for n in NAMES:
            self.assertNotIn(n, blob.casefold(), where)

    def test_the_brief_text_has_the_names(self):   # the one place they go: to the person
        text = jobs_runner.brief_apps_ask(self.st, NOW, self.env, self.dir)
        for n in NAMES:
            self.assertIn(n, text)

    def test_nowhere_else(self):
        text = jobs_runner.brief_apps_ask(self.st, NOW, self.env, self.dir)
        self.assertTrue(text)
        self.assertTrue(jobs_runner.brief_apps_ask_told(self.st, NOW, self.env, self.dir))
        self.assertNoName((self.st / apps_ask.MARK_FILE).read_text(), "mark")
        self.assertNoName(self.audit.read_text(), "tier audit log")
        for raw in ("0", "1"):
            env = dict(self.env, LIMITLESS_RAW_IN_PROMPT=raw)
            got = card.make_pre_llm_call(env=env, clock=lambda: NOW + D, today=lambda: date(2030, 1, 16))()
            self.assertNoName(json.dumps(got), f"state card raw={raw}")
            got = catchup.make_pre_llm_call(env=env, clock=lambda: NOW + D, home=self.dir)()
            self.assertNoName(json.dumps(got), f"catch-up hook raw={raw}")
        self.assertNoName(json.dumps(doctor.apps_ask_row(self.cfg, NOW, self.env)), "doctor row")
        self.assertNoName(json.dumps(doctor.report(self.cfg, NOW)), "doctor report")
        self.assertNoName(json.dumps([apps_ask.state(self.cfg, self.st, NOW, self.env)]), "state word")
        self.assertNoName(self.audit.read_text(), "tier audit log after the hooks")

    def test_the_audit_row_is_counts_and_a_hash(self):
        jobs_runner.brief_apps_ask(self.st, NOW, self.env, self.dir)
        row = json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual(row["hook"], "brief:apps_ask")
        self.assertEqual(set(row), set(tier_audit.event("brief:apps_ask", "x", False, NOW)))


if __name__ == "__main__":
    unittest.main()
