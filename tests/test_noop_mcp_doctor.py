"""limitless-doctor's NOOP MCP row: off without config noop_mcp; refused while t0_tools does not cover the server's
tools; else set, to be added to the host's mcp_servers by hand (the host has no plugin API for it). Words only:
no digit, no command, no env value and no server name. Starts no process. Synthetic config only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_noop_mcp import CMD, COVER, no_spawn  # noqa: E402

from limitless import doctor  # noqa: E402

NOW = 1894708800.0
# made-up values with digits and words that must never reach a row
DIGITY = {"command": ["noop-mcp-7", "--port", "8123"], "env": {"NOOP_DB": "/path/to/noop-42.db"},
          "name": "noop2"}


def bare(text):
    """The text without the config keys whose name holds a digit (doctor.CONFIG_KEYS_WITH_A_DIGIT)."""
    for key in doctor.CONFIG_KEYS_WITH_A_DIGIT:
        text = text.replace(key, "")
    return text


class Row(unittest.TestCase):
    def setUp(self):
        for p in no_spawn():
            p.start()
            self.addCleanup(p.stop)

    def check(self, cfg, status, reason):
        r = doctor.noop_mcp_row(cfg)
        self.assertEqual(r, {"name": doctor.NOOP_MCP_ROW, "kind": "mcp", "status": status, "reason": reason})
        self.assertNotRegex(bare(r["reason"]), r"\d")
        return r

    def test_off_by_default(self):
        r = self.check({}, doctor.OFF, "no noop_mcp set")
        self.assertEqual(doctor.text([r]), "NOOP MCP: off: no noop_mcp set")

    def test_refused_without_the_filter(self):
        for t0 in (None, [], ["mcp__noop__health_snapshot"], ["limitless_*"]):
            cfg = {"noop_mcp": {"command": CMD}, "t0_tools": t0}
            self.check(cfg, doctor.MISSING, "refused: t0_tools does not cover its tools")

    def test_set_and_covered_is_by_hand(self):
        self.check({"noop_mcp": {"command": CMD}, "t0_tools": [COVER]}, doctor.MISSING,
                   "set but the host cannot register MCP servers; add it to mcp_servers by hand")

    def test_malformed(self):
        self.check({"noop_mcp": {"command": "noop-agent-mcp"}}, doctor.MISSING,
                   "noop_mcp is set but is not a command list")

    def test_digit_walk(self):
        """Every state, with digits planted in the command, env and name: no row holds one, or any of them."""
        cfgs = ({}, {"noop_mcp": DIGITY}, {"noop_mcp": DIGITY, "t0_tools": ["mcp__noop2__*"]},
                {"noop_mcp": dict(DIGITY, command=[])})
        for cfg in cfgs:
            r = doctor.noop_mcp_row(cfg)
            out = doctor.text([r]) + doctor.as_json([r])
            self.assertNotRegex(bare(out), r"\d", cfg)
            for planted in ("noop-mcp", "--port", "/path/to", "NOOP_DB", "noop2"):
                self.assertNotIn(planted, out)


class Report(unittest.TestCase):
    def test_after_the_tools_not_strict_and_digit_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = Path(tmp) / "state"
            st.mkdir()
            cfg = {"state": str(st), "noop_mcp": DIGITY, "t0_tools": ["mcp__noop2__*"]}
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(cfg))
            old = os.environ.get("LIMITLESS_CONFIG")
            os.environ["LIMITLESS_CONFIG"] = str(path)
            try:
                rows = doctor.report(cfg, NOW)
            finally:
                if old is None:
                    del os.environ["LIMITLESS_CONFIG"]
                else:
                    os.environ["LIMITLESS_CONFIG"] = old
        names = [r["name"] for r in rows]
        self.assertEqual(names.count(doctor.NOOP_MCP_ROW), 1)
        at = names.index(doctor.NOOP_MCP_ROW)
        self.assertEqual(names[at - 1], "tool " + doctor.manifest_tools()[-1])
        self.assertEqual(names[at + 1], doctor.DESKTOP_AW_ROW)   # then the desktop AW row, the feed reflex,
        self.assertEqual(names[at + 2], doctor.FEED_REFLEX_ROW)  # then the apps lists, the apps ask,
        self.assertEqual(names[at + 3], doctor.APPS_ROW)         # the apps ingest job, the ranked ledger,
        self.assertEqual(names[at + 4], doctor.APPS_ASK_ROW)     # the ranked ingest job, then voice MIQ
        self.assertEqual(names[at + 5], doctor.APPS_INGEST_ROW)
        self.assertEqual(names[at + 6], doctor.RANKED_ROW)
        self.assertEqual(names[at + 7], doctor.RANKED_INGEST_ROW)
        self.assertEqual(names[at + 8], doctor.VOICE_MIQ_ROW)
        self.assertEqual(rows[at]["status"], doctor.MISSING)
        self.assertNotIn("mcp", doctor.STRICT_KINDS)
        for r in rows:
            self.assertNotRegex(bare(r["reason"]), r"\d", r)


if __name__ == "__main__":
    unittest.main()
