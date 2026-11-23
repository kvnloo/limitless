"""limitless.aw_desktop: the desktop ActivityWatch server (or a copied export) as app spans, read-only.

Synthetic buckets and events served by a fake fetch: no network, no real server. App names and window
titles are made up; a title is planted in every fixture so the tests can show it never comes out.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import aw_desktop  # noqa: E402

T0 = 2_000_000_000.0
M = 60.0
SECRET = "PLANTED-TITLE-zq"
URL = "http://aw.example.invalid:5600"


def iso(t: float, z: bool = False) -> str:
    s = datetime.fromtimestamp(t, timezone.utc).isoformat()
    return s.replace("+00:00", "Z") if z else s


def ev(start_m, end_m, **data):
    return {"id": 1, "timestamp": iso(T0 + start_m * M), "duration": (end_m - start_m) * M, "data": data}


def win(start_m, end_m, app="editor"):
    return ev(start_m, end_m, app=app, title=f"{SECRET} {app}")


def afk(start_m, end_m, status="not-afk"):
    return ev(start_m, end_m, status=status)


def server(windows=(), afks=(), host="desk-a", extra=None):
    b = {}
    if windows is not None:
        b[f"aw-watcher-window_{host}"] = {"id": f"aw-watcher-window_{host}", "type": "currentwindow",
                                          "hostname": host, "client": "aw-watcher-window",
                                          "events": list(windows)}
    if afks is not None:
        b[f"aw-watcher-afk_{host}"] = {"id": f"aw-watcher-afk_{host}", "type": "afkstatus", "hostname": host,
                                       "client": "aw-watcher-afk", "events": list(afks)}
    b.update(extra or {})
    return b


class FakeFetch:
    """Serves /api/0/buckets/ and /api/0/buckets/<id>/events like aw-server, from a dict of buckets."""

    def __init__(self, buckets, fail=None, body=None):
        self.buckets, self.fail, self.body, self.calls = buckets, fail, body, []

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if self.fail is not None:
            raise self.fail
        if self.body is not None:
            return self.body
        parts = urlsplit(url)
        path = parts.path
        if path == "/api/0/buckets/":
            return json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "events"}
                               for k, v in self.buckets.items()}).encode()
        prefix, suffix = "/api/0/buckets/", "/events"
        assert path.startswith(prefix) and path.endswith(suffix), path
        q = parse_qs(parts.query)
        assert q["limit"] == ["-1"], q
        assert "start" in q and "end" in q, q
        bid = path[len(prefix):-len(suffix)]
        return json.dumps(self.buckets[bid]["events"][::-1]).encode()   # newest first, as the server


def never(url, timeout):
    raise AssertionError("fetch must not be called")


class ReadEvents(unittest.TestCase):
    def read(self, buckets, since=0, until=600, **kw):
        f = FakeFetch(buckets, **kw)
        return aw_desktop.read_events(URL, T0 + since * M, T0 + until * M, fetch=f), f

    def test_window_spans_cut_to_not_afk(self):
        got, _ = self.read(server([win(0, 60), win(60, 90, "browser")], [afk(0, 20), afk(20, 40, "afk"),
                                                                           afk(40, 120)]))
        self.assertEqual(got["state"], aw_desktop.LIVE)
        self.assertEqual(got["events"], [(T0, T0 + 20 * M, "editor"), (T0 + 40 * M, T0 + 60 * M, "editor"),
                                         (T0 + 60 * M, T0 + 90 * M, "browser")])

    def test_away_time_is_removed_even_with_the_window_open(self):
        got, _ = self.read(server([win(0, 300)], [afk(0, 30), afk(30, 300, "afk")]))
        self.assertEqual(got["events"], [(T0, T0 + 30 * M, "editor")])

    def test_titles_never_leave_the_read(self):
        got, _ = self.read(server([win(0, 60), win(60, 90, "browser")], [afk(0, 120)]))
        text = json.dumps(got) + repr(got) + repr(aw_desktop.rows(got))
        self.assertNotIn(SECRET, text)
        self.assertNotIn("title\": \"PLANTED", text)
        for r in aw_desktop.rows(got):
            self.assertEqual(r["title"], "")

    def test_clipped_to_since_until(self):
        got, f = self.read(server([win(0, 60)], [afk(0, 60)]), since=10, until=50)
        self.assertEqual(got["events"], [(T0 + 10 * M, T0 + 50 * M, "editor")])
        q = parse_qs(urlsplit(f.calls[-1][0]).query)
        self.assertEqual(q["start"], [iso(T0 + 10 * M)])
        self.assertEqual(q["end"], [iso(T0 + 50 * M)])

    def test_newest_is_the_latest_active_window_end(self):
        got, _ = self.read(server([win(0, 60)], [afk(0, 45)]))
        self.assertEqual(got["newest"], T0 + 45 * M)

    def test_z_and_millisecond_timestamps(self):
        e = {"timestamp": iso(T0, z=True), "duration": 600.0, "data": {"app": "editor", "title": SECRET}}
        e2 = {"timestamp": "2033-05-18T03:33:20.250+00:00", "duration": 60, "data": {"app": "notes"}}
        got, _ = self.read(server([e, e2], [afk(0, 600)]))
        self.assertEqual([x[2] for x in got["events"]], ["editor", "notes"])
        self.assertEqual(got["events"][0][:2], (T0, T0 + 600))
        self.assertAlmostEqual(got["events"][1][0], T0 + 0.25)

    def test_bad_events_are_skipped_never_raise(self):
        bad = [{"timestamp": "nope", "duration": 1, "data": {"app": "x"}},
               {"timestamp": iso(T0), "duration": -5, "data": {"app": "x"}},
               {"timestamp": iso(T0), "duration": "long", "data": {"app": "x"}},
               {"timestamp": iso(T0), "duration": 60, "data": "x"},
               {"timestamp": iso(T0), "duration": 60, "data": {"app": ""}},
               {"timestamp": iso(T0), "duration": 60, "data": {"title": SECRET}},
               {"timestamp": iso(T0), "duration": True, "data": {"app": "x"}},
               "not an event", None, win(0, 10)]
        got, _ = self.read(server(bad, [afk(0, 60), {"timestamp": "x"}, "y"]))
        self.assertEqual(got["events"], [(T0, T0 + 10 * M, "editor")])

    def test_each_host_is_cut_by_its_own_afk_bucket(self):
        other = server([win(0, 60, "terminal")], [afk(0, 60, "afk")], host="desk-b")
        got, _ = self.read(server([win(0, 60)], [afk(0, 60)], extra=other))
        self.assertEqual(got["events"], [(T0, T0 + 60 * M, "editor")])
        self.assertNotIn("desk-", json.dumps(got))

    def test_no_afk_bucket_is_unknown_not_all_active(self):
        got, _ = self.read(server([win(0, 60)], None))
        self.assertIsNone(got["events"])
        self.assertEqual(got["state"], aw_desktop.UNKNOWN)
        self.assertEqual(got["why"], aw_desktop.NO_AFK)

    def test_no_window_bucket_is_unknown(self):
        got, _ = self.read(server(None, [afk(0, 60)]))
        self.assertIsNone(got["events"])
        self.assertEqual(got["why"], aw_desktop.NO_WINDOW)

    def test_known_and_empty_is_an_empty_list_not_unknown(self):
        got, _ = self.read(server([], []))
        self.assertEqual(got["events"], [])
        self.assertEqual(got["state"], aw_desktop.LIVE)
        self.assertIsNone(got["newest"])

    def test_the_timeout_is_short(self):
        _, f = self.read(server([win(0, 60)], [afk(0, 60)]))
        self.assertTrue(f.calls)
        for _, t in f.calls:
            self.assertGreater(t, 0)
            self.assertLessEqual(t, 5)

    def test_a_network_error_is_unknown_and_never_raises(self):
        for err in (OSError("refused"), TimeoutError(), ValueError("bad"), RuntimeError("boom")):
            got, _ = self.read({}, fail=err)
            self.assertIsNone(got["events"])
            self.assertEqual(got["state"], aw_desktop.UNREACHABLE)
            self.assertEqual(got["why"], aw_desktop.NO_ANSWER)

    def test_a_body_that_is_not_aw_data_is_unknown(self):
        for body in (b"<html>", b"[]", b"\xff\xfe", b'{"x": 1}', b"null"):
            got, _ = self.read({}, body=body)
            self.assertIsNone(got["events"], body)
            self.assertIn(got["why"], (aw_desktop.NOT_AW, aw_desktop.NO_WINDOW))

    def test_only_http_addresses_are_fetched(self):
        for url in ("file:///etc/passwd", "ftp://x", "", "   ", None, 5, "aw.example.invalid"):
            got = aw_desktop.read_events(url, T0, T0 + 60, fetch=never)
            self.assertIsNone(got["events"])
            self.assertEqual(got["why"], aw_desktop.BAD_URL)

    def test_reasons_are_path_and_digit_free(self):
        reasons = [aw_desktop.OFF_WHY, aw_desktop.NO_AFK, aw_desktop.NO_WINDOW, aw_desktop.NO_ANSWER,
                   aw_desktop.NOT_AW, aw_desktop.BAD_URL, aw_desktop.NO_EXPORT]
        for why in reasons:
            self.assertFalse(any(c.isdigit() for c in why), why)
            self.assertNotIn("/", why)
            self.assertNotIn("example", why)


class ReadExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_export_file_reads_the_same_as_the_server(self):
        b = server([win(0, 60), win(60, 90, "browser")], [afk(0, 20), afk(20, 40, "afk"), afk(40, 120)])
        p = self.dir / "aw-buckets-export.json"
        p.write_text(json.dumps({"buckets": b}))
        got = aw_desktop.read_export(p, T0, T0 + 600 * M)
        live = aw_desktop.read_events(URL, T0, T0 + 600 * M, fetch=FakeFetch(b))
        self.assertEqual(got["events"], live["events"])
        self.assertEqual(got["state"], aw_desktop.LIVE)
        self.assertNotIn(SECRET, json.dumps(got))

    def test_a_missing_or_broken_export_is_unknown_without_its_path(self):
        p = self.dir / "secret-folder-name" / "x.json"
        got = aw_desktop.read_export(p, T0, T0 + 60)
        self.assertIsNone(got["events"])
        self.assertEqual(got["why"], aw_desktop.NO_EXPORT)
        self.assertNotIn("secret-folder-name", json.dumps(got))
        bad = self.dir / "bad.json"
        for body in ("{", "[]", '{"buckets": 3}'):
            bad.write_text(body)
            got = aw_desktop.read_export(bad, T0, T0 + 60)
            self.assertIsNone(got["events"], body)
        self.assertIsNone(aw_desktop.read_export(None, T0, T0 + 60)["events"])


class FromConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **kv):
        self.cfg.write_text(json.dumps(kv))

    def test_unset_is_off_and_no_fetch_is_called(self):
        self.config(aw_db="x.db")
        got = aw_desktop.for_config(self.env, self.dir, T0, T0 + 60, fetch=never)
        self.assertEqual(got, {"events": None, "state": aw_desktop.OFF, "why": aw_desktop.OFF_WHY, "newest": None})
        self.assertFalse(aw_desktop.configured(self.env, self.dir))
        self.assertIsNone(aw_desktop.rows(got))
        for v in ("", "  ", None, 3, []):
            self.config(desktop_aw_url=v)
            self.assertEqual(aw_desktop.for_config(self.env, self.dir, T0, T0 + 60, fetch=never)["state"],
                             aw_desktop.OFF)

    def test_url_reads_the_server(self):
        self.config(desktop_aw_url=URL)
        f = FakeFetch(server([win(0, 60)], [afk(0, 60)]))
        got = aw_desktop.for_config(self.env, self.dir, T0, T0 + 60 * M, fetch=f)
        self.assertTrue(aw_desktop.configured(self.env, self.dir))
        self.assertEqual(got["events"], [(T0, T0 + 60 * M, "editor")])
        self.assertTrue(f.calls[0][0].startswith(URL + "/api/0/buckets/"))

    def test_a_trailing_slash_in_the_url_is_fine(self):
        self.config(desktop_aw_url=URL + "/")
        f = FakeFetch(server([win(0, 60)], [afk(0, 60)]))
        aw_desktop.for_config(self.env, self.dir, T0, T0 + 60 * M, fetch=f)
        self.assertEqual(f.calls[0][0], URL + "/api/0/buckets/")

    def test_export_path_reads_the_file_relative_to_the_state_dir(self):
        st = self.dir / "state"
        st.mkdir()
        (st / "desk.json").write_text(json.dumps({"buckets": server([win(0, 60)], [afk(0, 60)])}))
        self.config(state=str(st), desktop_aw_export="desk.json")
        got = aw_desktop.for_config(self.env, self.dir, T0, T0 + 60 * M, fetch=never)
        self.assertEqual(got["events"], [(T0, T0 + 60 * M, "editor")])

    def test_rows_are_the_blocks_row_shape_labelled_desktop(self):
        got = {"events": [(T0, T0 + 60, "Editor")], "state": aw_desktop.LIVE, "why": "", "newest": T0 + 60}
        self.assertEqual(aw_desktop.rows(got), [{"start": T0, "end": T0 + 60, "names": ["editor"], "title": "",
                                                 "source": "desktop"}])


if __name__ == "__main__":
    unittest.main()
