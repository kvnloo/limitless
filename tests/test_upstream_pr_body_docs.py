"""docs/upstream/hermes-pr-decision-window.md holds the upstream Hermes PR title and body for the cron
decision-window gate: a short conventional title, the upstream template's sections, the design-comment link,
every test file the fork branch adds, and nothing private (no host, path, person or real-data number)."""
import hermetic_env  # noqa: F401  first import: isolates HOME, see tests/hermetic_env.py
import re
import unittest
from pathlib import Path

from test_public_hygiene import BAD

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "upstream" / "hermes-pr-decision-window.md"

# Copied from the fork branch up/cron-decision-window-gate (head 16a9936):
# git diff --name-status --diff-filter=A <merge-base> <head> -- tests/
FORK_TEST_FILES = (
    "tests/cron/test_decision_window.py",
    "tests/cron/test_window_gate_tick.py",
    "tests/hermes_cli/test_plugin_window_provider.py",
)
# The upstream .github/PULL_REQUEST_TEMPLATE.md sections, in order (the skill section is dropped: no skill here).
TEMPLATE_SECTIONS = ("What does this PR do?", "Related Issue", "Type of Change", "Changes Made", "How to Test",
                     "Checklist", "Screenshots / Logs")
COMMENT_URL = "https://github.com/NousResearch/hermes-agent/issues/158538#issuecomment-7086516039"
# Beyond the repo-wide hygiene patterns: what a PR body drafted from a personal setup could leak.
PRIVATE = [
    (r"/home/|/Users/|/root/|[A-Za-z]:\\\\Users", "private path"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "ip address"),
    (r"(?i)\b[\w-]+\.(?:local|lan|internal|home|ts\.net)\b", "host name"),
    (r"(?i)\b(?:localhost|tailnet|tailscale)\b", "host name"),
    (r"[\w.+-]+@[\w-]+\.[\w.]+", "email"),
    (r"(?<![\w.`])@[A-Za-z][\w-]+", "person handle"),
    (r"(?i)\b(?:kevin|rajan|kvn|kvnloo|tek|teknium1?)\b", "person"),
    (r"(?i)\b\d+(?:\.\d+)?\s*(?:bpm|kg|kgs|lbs?|mmhg|kcal|steps|ms\b|%)", "health number"),
    (r"(?i)\b(?:hrv|spo2|resting heart|heart rate|weight|slept|sleep score)\b", "health metric"),
    (r"(?i)\b(?:pixel|galaxy|iphone|ipad|macbook|mac mini|mac studio|oura|whoop|fitbit|garmin)\b", "device"),
    (r"(?<![\w-])\+?\d{3}[ .-]\d{3}[ .-]\d{4}(?![\w-])", "phone number"),
    (r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{8,}\b", "serial number"),
    # a digit run glued to a letter (a short git sha like a910662) is not a standalone number;
    # the design-comment id is the one allowed, see below
    (r"(?<![\w#/-])\d{6,}(?![\d-])", "long number"),
]


def _fenced(text, heading, lang):
    m = re.search(rf"^## {re.escape(heading)}\n+```{lang}\n(.*?)^```$", text, re.S | re.M)
    return m.group(1) if m else None


class UpstreamPrBody(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DOC.is_file(), f"missing {DOC.relative_to(ROOT)}")
        self.text = DOC.read_text()
        self.body = _fenced(self.text, "Body", "markdown")
        self.assertIsNotNone(self.body, "the body is one ```markdown block under '## Body'")

    def test_the_title_is_one_short_conventional_line(self):
        title = _fenced(self.text, "Title", "text")
        self.assertIsNotNone(title, "the title is one ```text block under '## Title'")
        lines = title.strip("\n").splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertLess(len(lines[0]), 72, lines[0])
        self.assertRegex(lines[0], r"^(feat|fix|docs|test|refactor|chore)\([a-z_-]+\): \S")

    def test_the_body_uses_the_upstream_template_sections_in_order(self):
        heads = re.findall(r"^## (.+)$", self.body, re.M)
        self.assertEqual([h for h in heads if h in TEMPLATE_SECTIONS], list(TEMPLATE_SECTIONS))
        self.assertIn("Not in this PR", heads)
        self.assertNotIn("For New Skills", heads)

    def test_the_body_says_what_changes_without_a_provider_and_links_the_design(self):
        self.assertIn("Users who never register a window provider: nothing changes.", self.body)
        self.assertIn(COMMENT_URL, self.body)
        self.assertIn("Part of #158538", self.body)
        self.assertNotRegex(self.body, r"(?i)\b(fixes|closes|resolves) #158538", "the roadmap issue stays open")

    def test_the_body_lists_every_test_file_the_fork_branch_adds(self):
        how = self.body.split("## How to Test", 1)[1].split("\n## ", 1)[0]
        changes = self.body.split("## Changes Made", 1)[1].split("\n## ", 1)[0]
        for path in FORK_TEST_FILES:
            self.assertIn(path, changes)
            self.assertIn(path, how)
        step1 = next(line for line in how.splitlines() if line.strip().startswith("`just test"))
        self.assertEqual(re.findall(r"tests/\S+\.py", step1), list(FORK_TEST_FILES))

    def test_the_not_in_this_pr_list_keeps_plugin_pieces_out(self):
        rest = self.body.split("## Not in this PR", 1)[1].split("\n## ", 1)[0]
        for piece in ("provider itself", "send gate", "evidence envelope"):
            self.assertIn(piece, rest)

    def test_no_host_private_path_person_or_real_data_number(self):
        text = self.text.replace(COMMENT_URL, "")
        hits = [f"{what}: {m.group(0)}" for pat, what in BAD + PRIVATE for m in re.finditer(pat, text)]
        self.assertEqual(hits, [])

    def test_the_private_patterns_catch_each_shape(self):
        for sample in ("/home/someone/x", "10.0.0.7", "box.local", "a@b.example", "@someone", "Kevin",
                       "62 bpm", "HRV", "Pixel", "555-123-4567", "ZX9Q81234AB", "1234567"):
            self.assertTrue(any(re.search(pat, sample) for pat, _ in BAD + PRIVATE), sample)
        for fine in ("#158538", "16a9936", "a910662", "2026-01-05T12:00:00+00:00", "stale_after_s=3600", "`ctx.register_x`"):
            self.assertFalse([w for pat, w in BAD + PRIVATE if re.search(pat, fine)], fine)

    def test_every_date_is_the_synthetic_fixture_date(self):
        self.assertEqual(set(re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", self.text)), {"2026-01-05"})


if __name__ == "__main__":
    unittest.main()
