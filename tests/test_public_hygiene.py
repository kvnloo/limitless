"""The repo is public: no personal data, private paths, hostnames or secrets in any tracked file."""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAD = [
    (r"/mnt/zer0models|/home/kvn|/Users/kvn", "private path"),
    (r"\b\d{8,10}:[A-Za-z0-9_-]{30,}", "telegram bot token"),
    (r"(?i)\b(api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]{8,}", "credential"),
    (r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "tailnet address"),
    (r"(?i)\.ts\.net\b", "tailnet hostname"),
    (r"(?i)\bchat_id\s*[:=]\s*-?\d{5,}", "chat id"),
    (r"\b(R5CY|RFCTA)[0-9A-Z]{5,}", "device serial"),
]


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return [ROOT / p for p in out if p != "tests/test_public_hygiene.py"]


class PublicHygiene(unittest.TestCase):
    def test_no_private_strings(self):
        hits = []
        for f in tracked():
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            for pat, what in BAD:
                for m in re.finditer(pat, text):
                    hits.append(f"{f.relative_to(ROOT)}: {what}: {m.group(0)[:40]}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_data_files(self):
        data = [str(f.relative_to(ROOT)) for f in tracked()
                if f.suffix in {".db", ".sqlite", ".sqlite3", ".csv"}
                or (f.suffix in {".jsonl", ".json"} and "fixtures" not in f.parts)]
        self.assertEqual(data, [])


if __name__ == "__main__":
    unittest.main()
