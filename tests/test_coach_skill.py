"""skills/coach/SKILL.md: the plugin's own coach skill (limitless:coach) stays short, names only real tools,
covers every tool in plugin.yaml, and never holds a clock time or a dosing word."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_plugin import manifest_list  # noqa: E402

from limitless.envelope import MODALITIES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "coach" / "SKILL.md"
MAX_LINES = 120
# tools in plugin.yaml the question -> tool table may leave out on purpose (none today)
TABLE_EXCEPTIONS = set()
TIERS = ("direct", "indirect", "stale", "none")
CLOCK = [re.compile(r"(?i)\b\d{1,2}(:\d\d)? ?(am|pm)\b"), re.compile(r"\b\d{1,2}:\d\d\b")]
DOSING = ["mg", "mcg", "milligram", "milligrams", "microgram", "micrograms", "iu", "dose", "doses", "dosage",
          "dosages", "dosing", "supplement", "supplements", "supplementation", "melatonin", "caffeine amount",
          "caffeine dose", "how much caffeine", "titrate", "prescribe", "prescription"]


def text():
    return SKILL.read_text()


def frontmatter(src):
    """Flat ``key: value`` frontmatter between the two leading ``---`` lines (quotes stripped)."""
    lines = src.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("no frontmatter")
    end = lines.index("---", 1)
    out = {}
    for ln in lines[1:end]:
        if not ln.strip() or ln.startswith(" "):
            continue
        key, sep, val = ln.partition(":")
        if not sep:
            raise ValueError(f"bad frontmatter line {ln!r}")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key.strip()] = val
    return out, "\n".join(lines[end + 1:])


def table_tools(body):
    return {t for ln in body.split("\n") if ln.startswith("|") for t in re.findall(r"limitless_[a-z_]+", ln)}


class Format(unittest.TestCase):
    def test_frontmatter_parses_and_the_name_is_coach(self):
        fm, body = frontmatter(text())
        self.assertEqual(fm["name"], "coach")
        self.assertTrue(fm["description"])
        self.assertTrue(body.strip())

    def test_the_name_is_a_valid_bare_skill_name(self):
        name = frontmatter(text())[0]["name"]
        self.assertRegex(name, r"^[a-zA-Z0-9_-]+$")
        self.assertNotIn(":", name)

    def test_short(self):
        self.assertLessEqual(len(text().split("\n")), MAX_LINES)


class Tools(unittest.TestCase):
    def test_every_tool_named_is_in_plugin_yaml(self):
        named = set(re.findall(r"limitless_[a-z_]+", text()))
        self.assertTrue(named)
        self.assertEqual(sorted(named - set(manifest_list("provides_tools"))), [])

    def test_the_table_covers_every_tool_but_the_listed_exceptions(self):
        body = frontmatter(text())[1]
        missing = set(manifest_list("provides_tools")) - table_tools(body) - TABLE_EXCEPTIONS
        self.assertEqual(sorted(missing), [])

    def test_exceptions_are_real_tools_left_out_of_the_table(self):
        self.assertEqual(TABLE_EXCEPTIONS - set(manifest_list("provides_tools")), set())
        self.assertEqual(TABLE_EXCEPTIONS & table_tools(frontmatter(text())[1]), set())


class Never(unittest.TestCase):
    def test_no_clock_time(self):
        hits = [m.group(0) for pat in CLOCK for m in pat.finditer(text())]
        self.assertEqual(hits, [])

    def test_no_dosing_words(self):
        low = text().lower()
        hits = [w for w in DOSING if re.search(r"\b" + re.escape(w) + r"\b", low)]
        self.assertEqual(hits, [])

    def test_no_capability_score_offered(self):
        self.assertNotRegex(text().lower(), r"\byour (score|level|xp)\b")


class Contract(unittest.TestCase):
    def test_the_four_steps_in_order(self):
        low = frontmatter(text())[1].lower()
        idx = [low.find(w) for w in ("explain", "suggest", "prepare", "commit")]
        self.assertNotIn(-1, idx, idx)
        self.assertEqual(idx, sorted(idx))

    def test_names_every_modality_and_evidence_tier(self):
        body = frontmatter(text())[1]
        for word in MODALITIES + TIERS:
            self.assertRegex(body, r"\b" + re.escape(word) + r"\b", word)

    def test_the_rules_the_brief_asks_for(self):
        low = " ".join(frontmatter(text())[1].lower().split())   # markdown wraps lines anywhere
        for phrase in ("unknown is never zero", "skipped", "unlogged", "one habit a week", "event",
                       "never a clock time", "send gate", "never a direct message", "t2", "opt-in",
                       "confirm: true", "no_suggestion", "diagnos"):
            self.assertTrue(phrase in low, phrase)


if __name__ == "__main__":
    unittest.main()
