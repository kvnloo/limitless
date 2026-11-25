"""One name in words per job (jobs.JOB_WORDS), read by every doctor row, schedule card and cron-spec line.

A job id (``habit_checkin``, ``miq``) is a key, not words: a person reads these lines, so one job has one name
everywhere and no line builds it from the id. Synthetic temp dirs and config only; no clock, no network.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermetic_env import child_env

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import cron_spec, doctor, jobs, schedule_cards  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = 1894708800.0   # a synthetic clock; nothing here depends on the hour
IDS = [s.name for s in cron_spec.all_specs()] + [schedule_cards.LEDGER_ID]
SENDING = [s.name for s in cron_spec.all_specs() if cron_spec.job_spec(s)]
# Machine names a line may carry on purpose: a host job or script name the operator types (limitless-<id>), a config
# key (config outage_recap, config flow_work_apps, feed_apps) and a tool name (tool limitless_status).
_MACHINE = re.compile(r"limitless[-_][a-z_]+(\.sh)?|\bconfig\s+[a-z_]+(,\s*[a-z_]+)*")
ALL_CARDS = dict(ledger=True, noop=True, apps=True, ranked=True, recap=True, sender=True, confirm=True, fit=True)


def raw_ids(line):
    """The job ids written into ``line`` as an id (underscored, or a lowercase ``miq``), machine names aside."""
    text = _MACHINE.sub(" ", line)
    found = [i for i in IDS if "_" in i and re.search(rf"(?<![\w-]){i}(?!\w)", text)]
    return found + (["miq"] if re.search(r"\bmiq\b", text) else [])


class Table(unittest.TestCase):
    def test_every_job_id_has_its_words(self):
        for i in IDS:
            with self.subTest(job=i):
                self.assertIn(i, jobs.JOB_WORDS)
                self.assertEqual(jobs.job_words(i), jobs.JOB_WORDS[i])

    def test_the_words_are_words(self):
        for i, w in jobs.JOB_WORDS.items():
            with self.subTest(job=i):
                self.assertTrue(w.strip() and w == w.strip(), w)
                self.assertNotIn("_", w)
                self.assertFalse(re.search(r"\d", w), w)
                self.assertEqual(raw_ids(w), [], w)

    def test_one_job_one_name(self):
        self.assertEqual(len(set(jobs.JOB_WORDS.values())), len(jobs.JOB_WORDS))

    def test_the_names_the_cards_and_docs_use(self):
        for i, w in (("wake_brief", "wake brief"), ("miq", "MIQ"), ("habit_checkin", "habit check-in"),
                     ("week_review", "week review"), ("break_nudge", "break nudge"), ("outage_recap", "outage recap"),
                     ("sender_confirm", "sender confirmation"), ("noop_export", "NOOP export"),
                     ("fit_ingest", "FIT import")):
            with self.subTest(job=i):
                self.assertEqual(jobs.JOB_WORDS[i], w)

    def test_an_unknown_id_is_not_guessed(self):
        with self.assertRaises(KeyError):
            jobs.job_words("synthetic_job")


class DoctorNames(unittest.TestCase):
    def test_job_names_reads_the_table(self):
        self.assertEqual(doctor.job_names(["miq"]), "MIQ")
        self.assertEqual(doctor.job_names(["wake_brief", "miq", "habit_checkin"]),
                         "wake brief, MIQ and habit check-in")

    def test_job_names_says_every_sending_job_by_its_words(self):
        said = doctor.job_names(SENDING)
        for i in SENDING:
            with self.subTest(job=i):
                self.assertIn(jobs.JOB_WORDS[i], said)

    def test_job_names_never_guesses_from_an_id(self):
        with self.assertRaises(KeyError):
            doctor.job_names(["synthetic_job"])

    def test_job_rows_are_named_from_the_table(self):
        for row, i in ((doctor.NOOP_ROW, "noop_export"), (doctor.APPS_INGEST_ROW, "apps_ingest"),
                       (doctor.RANKED_INGEST_ROW, "ranked_ingest"), (doctor.SENDER_INGEST_ROW, "sender_ingest"),
                       (doctor.FIT_IMPORT_ROW, "fit_ingest"), (doctor.SENDER_CONFIRM_ROW, "sender_confirm"),
                       (doctor.OUTAGE_RECAP_ROW, "outage_recap")):
            with self.subTest(job=i):
                self.assertEqual(row, f"job {jobs.JOB_WORDS[i]}")


class EveryLine(unittest.TestCase):
    """Walk the doctor report, the schedule cards and the cron-spec lines built from a synthetic config."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def config(self, records):
        st, scripts = self.root / "state", self.root / "scripts"
        st.mkdir(exist_ok=True)
        scripts.mkdir(exist_ok=True)
        jobs_file = self.root / "jobs.json"
        jobs_file.write_text(json.dumps({"jobs": records}), encoding="utf-8")
        cfg = {"state": str(st), "host_scripts_dir": str(scripts), "host_jobs_file": str(jobs_file)}
        for key in ("noop_export", "apps_ingest", "ranked_ingest", "sender_ingest", "fit_ingest", "outage_recap",
                    "sender_confirm", "voice_miq"):
            cfg[key] = "dry_run"
        return cfg

    def doctor_lines(self, records):
        return doctor.text(doctor.report(self.config(records), NOW)).splitlines()

    @staticmethod
    def card_lines():
        out = []
        for c in schedule_cards.cards(**ALL_CARDS):
            out += [c["name"], c["job"], c["description"]] + [v for v in c["words"].values() if isinstance(v, str)]
        return out

    def assertNoRawId(self, lines):
        self.assertTrue(lines)
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(raw_ids(line), [])

    def test_the_doctor_with_no_job_on_the_host(self):
        lines = self.doctor_lines([])
        self.assertNoRawId(lines)
        absent = next(ln for ln in lines if ln.startswith(doctor.HOST_JOBS_ROW + ":"))
        self.assertIn(f"{doctor.HOST_JOBS_ABSENT}: {doctor.job_names(SENDING)}", absent)

    def test_the_doctor_with_every_job_differing(self):
        records = [dict(p, schedule={"kind": "interval", "minutes": 1}, window_class="trough")
                   for p in cron_spec.payloads()]
        lines = self.doctor_lines(records)
        self.assertNoRawId(lines)
        differ = next(ln for ln in lines if ln.startswith(doctor.HOST_JOBS_ROW + ":"))
        self.assertIn(f"{doctor.HOST_JOBS_DIFFER}: {doctor.job_names(SENDING)}", differ)

    def test_the_schedule_cards(self):
        self.assertNoRawId(self.card_lines())

    def test_every_card_names_its_job_from_the_table(self):
        for c in schedule_cards.cards(**ALL_CARDS):
            with self.subTest(job=c["id"]):
                self.assertEqual(c["job"], jobs.JOB_WORDS[c["id"]])

    def test_the_cron_spec_word_lines(self):
        self.assertNoRawId(cron_spec.plan_lines())
        for line, spec in zip(cron_spec.plan_lines(), cron_spec.all_specs()):
            with self.subTest(job=spec.name):
                self.assertTrue(line.startswith(f"limitless-{spec.name} ({jobs.JOB_WORDS[spec.name]}): "), line)

    def test_the_cron_spec_cli_word_lines(self):
        home = self.root / "home"
        home.mkdir()
        r = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "limitless-cron-spec")],
                           env=child_env({"PATH": "/usr/bin:/bin"}, HOME=str(home)), capture_output=True, text=True,
                           timeout=60, cwd=str(home))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), cron_spec.plan_lines())


if __name__ == "__main__":
    unittest.main()
