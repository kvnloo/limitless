"""Every failure of the Open Wearables export is one plain reason in words, exit 1 and nothing written; the API key
(a synthetic string here) never appears in any output, reason, exception text or mark, and is never read from
config.json.

Synthetic only; the http callable is injected, so nothing touches the network.
"""
import io
import json
import socket
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import open_wearables as ow  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "open_wearables"
UTC = timezone.utc
KEY = "ow-SYNTHETIC-key-7f3a9c"
USER = "00000000-0000-4000-8000-0000000000aa"
URL = "http://ow.example.invalid:8000"
OLD = '{"night": "2029-12-01", "asleep_s": 25000, "source": "noop"}\n'


def answer(*items):
    items = list(items)

    def http(url, headers, timeout):
        got = items.pop(0)
        if isinstance(got, BaseException):
            raise got
        return got
    return http


PAGE1 = (200, (FIX / "sleep_page1.json").read_bytes())
CASES = {   # name -> (http answers, the one reason)
    "refused": ([(401, b'{"detail": "bad key"}')], ow.REFUSED),
    "forbidden": ([(403, b"")], ow.REFUSED),
    "not found": ([(404, b"")], ow.NOT_FOUND),
    "server error": ([(500, b"oops")], ow.HTTP_ERROR),
    "server error on the second page": ([PAGE1, (502, b"")], ow.HTTP_ERROR),
    "timeout": ([socket.timeout(f"timed out {KEY}")], ow.TIMEOUT),
    "timeout inside urllib": ([urllib.error.URLError(socket.timeout(KEY))], ow.TIMEOUT),
    "unreachable": ([urllib.error.URLError(f"refused {KEY}")], ow.UNREACHABLE),
    "os error": ([ConnectionRefusedError(f"refused {KEY}")], ow.UNREACHABLE),
    "bad header value": ([ValueError(f"Invalid header value {KEY!r}")], ow.UNREACHABLE),
    "anything else": ([RuntimeError(KEY)], ow.UNREACHABLE),
    "not json": ([(200, b"<html>" + KEY.encode() + b"</html>")], ow.BAD_JSON),
    "not utf-8": ([(200, b"\xff\xfe")], ow.BAD_JSON),
    "a list, not the page": ([(200, b"[]")], ow.BAD_JSON),
    "no data list": ([(200, b'{"data": {"x": 1}}')], ow.BAD_JSON),
}


class Reasons(unittest.TestCase):
    def test_each_failure_is_one_reason_and_no_rows(self):
        for name, (answers, reason) in CASES.items():
            with self.subTest(name):
                got = ow.fetch_sleep(URL, KEY, date(2030, 1, 1), http=answer(*answers), user=USER,
                                     until=date(2030, 1, 8), tz=UTC)
                self.assertEqual(got, {"sleep": [], "reason": reason, "skipped": {}})
                self.assertIn(reason, ow.REASONS)

    def test_missing_settings(self):
        never = answer()
        for args, reason in (((None, KEY, USER), ow.NO_URL), (("  ", KEY, USER), ow.NO_URL),
                             (("ftp://ow.example.invalid", KEY, USER), ow.BAD_URL),
                             (("ow.example.invalid:8000", KEY, USER), ow.BAD_URL),
                             ((URL, KEY, None), ow.NO_USER), ((URL, None, USER), ow.NO_KEY),
                             ((URL, " ", USER), ow.NO_KEY)):
            with self.subTest(reason=reason, args=args[0]):
                got = ow.fetch_sleep(args[0], args[1], date(2030, 1, 1), http=never, user=args[2])
                self.assertEqual(got["reason"], reason)

    def test_no_reason_has_a_digit_or_the_key(self):
        for r in ow.REASONS:
            self.assertFalse(any(ch.isdigit() for ch in r), r)
            self.assertNotIn(KEY, r)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.state = self.home / "state"
        self.state.mkdir()
        self.sleep = self.state / "sleep.jsonl"
        self.sleep.write_text(OLD)
        self.cfg = {"state": str(self.state), "sleep_file": "sleep.jsonl", "open_wearables_export": "write",
                    "open_wearables_url": URL, "open_wearables_user": USER}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, http, cfg=None, key=KEY, argv=("--write",)):
        p = self.home / "config.json"
        p.write_text(json.dumps(self.cfg if cfg is None else cfg))
        env = {"LIMITLESS_CONFIG": str(p)}
        if key is not None:
            env["LIMITLESS_OW_KEY"] = key
        out, err = io.StringIO(), io.StringIO()
        code = ow.main(list(argv), env=env, home=self.home, tz=UTC, out=out, err=err, http=http,
                       today=date(2030, 1, 8), now=1893456000.0)
        return code, out.getvalue(), err.getvalue()

    def everything(self, out, err):
        texts = [out, err] + [p.read_text(errors="replace") for p in self.state.iterdir()]
        return "\n".join(texts)

    def test_each_failure_exits_one_with_the_reason_and_writes_nothing(self):
        for name, (answers, reason) in CASES.items():
            for argv in (["--write"], []):
                with self.subTest(name, argv=argv):
                    code, out, err = self.run_cli(answer(*answers), argv=argv)
                    self.assertEqual(code, 1)
                    self.assertEqual(err.strip(), reason)
                    self.assertEqual(self.sleep.read_text(), OLD)
                    blob = self.everything(out, err)
                    self.assertNotIn(KEY, blob)
                    self.assertNotIn("SYNTHETIC", blob)
                    self.assertNotIn(USER, blob)
                    self.assertNotIn("example.invalid", blob)
                    mark = ow.load_mark(self.state)
                    self.assertEqual((mark["outcome"], mark["said"]), (ow.FAILED, reason))

    def test_no_url_no_user_no_key(self):
        for cfg, key, reason in (({k: v for k, v in self.cfg.items() if k != "open_wearables_url"}, KEY, ow.NO_URL),
                                 ({k: v for k, v in self.cfg.items() if k != "open_wearables_user"}, KEY, ow.NO_USER),
                                 (self.cfg, None, ow.NO_KEY)):
            with self.subTest(reason):
                code, out, err = self.run_cli(answer(), cfg=cfg, key=key)
                self.assertEqual((code, err.strip()), (1, reason))
                self.assertEqual(self.sleep.read_text(), OLD)

    def test_the_key_is_never_read_from_config_json(self):
        cfg = dict(self.cfg, open_wearables_key=KEY, LIMITLESS_OW_KEY=KEY)
        code, _, err = self.run_cli(answer(), cfg=cfg, key=None)
        self.assertEqual((code, err.strip()), (1, ow.NO_KEY))

    def test_a_successful_run_never_prints_or_marks_the_key(self):
        pages = [(200, (FIX / n).read_bytes()) for n in ("sleep_page1.json", "sleep_page2.json")]
        code, out, err = self.run_cli(answer(*pages))
        self.assertEqual(code, 0)
        blob = self.everything(out, err)
        for secret in (KEY, USER, "example.invalid", "polar", "Synthetic Sleep App"):
            self.assertNotIn(secret, blob)

    def test_the_key_is_sent_only_in_the_documented_header(self):
        seen = []

        def http(url, headers, timeout):
            seen.append((url, headers))
            return 200, b'{"data": [], "pagination": {"has_more": false}}'
        self.run_cli(http)
        (url, headers), = seen
        self.assertNotIn(KEY, url)
        self.assertEqual([k for k, v in headers.items() if v == KEY], [ow.HEADER])


if __name__ == "__main__":
    unittest.main()
