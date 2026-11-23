# Desktop ActivityWatch: a second app-activity source, read-only

The flow features (focus blocks and the break nudge, flow metrics, the flow ledger, the weekly flow line)
read app activity from the phone's ActivityWatch DB copy (`aw_db`). Most work happens at a desktop, so the
desktop's own ActivityWatch can feed the same features: `limitless/aw_desktop.py` reads it, and
`blocks.source_rows` joins its rows to the phone's, each row labelled `source` "phone" or "desktop". There is
no second store and nothing is written: the desktop server is read on demand.

## Set it

One of these in the host config (`~/.config/limitless/config.json` or `$LIMITLESS_CONFIG`):

- `desktop_aw_url`: the desktop's aw-server, for example `http://localhost:5600` on the same machine.
  Read with `GET /api/0/buckets/` and `GET /api/0/buckets/<id>/events?start=&end=&limit=-1`, timeout two
  seconds (`aw_desktop.TIMEOUT_S`). A server that does not answer is not asked again for five minutes
  (`HOLD_S`), so an asleep desktop does not slow the card.
- `desktop_aw_export`: a copied aw-server export file (`GET /api/0/export`, or the web UI's export:
  `{"buckets": {<id>: {..., "events": [...]}}}`) for a host with no network path to the desktop. A
  relative path is in the state dir. `desktop_aw_url` wins when both are set.

Unset is off: no network call and no file read, and every flow feature answers exactly as before (the
regression pin in `tests/test_aw_desktop_flow.py`). `flow_work_apps` and `feed_apps` apply to both sources.

## What is read, and what is never kept

Buckets are found by `type`, never by name (aw-server docs, `buckets-and-events.rst`):

- `currentwindow`: event `data` has `app` and `title`. Only `app` is read. The window title is T0 and is
  dropped at read time: it is in no return value, no row, no reason and no log. A `title:` entry in
  `flow_work_apps` therefore matches phone rows only.
- `afkstatus`: event `data.status` is "afk" or "not-afk". Window time is cut to the not-afk time of the afk
  bucket on the same host: a window left open while the person is away is not activity.

Host names and bucket ids are not kept. Event `timestamp` is ISO-8601 (UTC from aw-server) and `duration`
is in seconds.

## Unknown is never zero

- The desktop is set and does not answer, sends something that is not ActivityWatch data, has no window
  bucket, or has a window bucket and no afk bucket (away time could not be removed): every flow feature is
  unknown with that reason, plain and digit-free. A missing desktop never reads as "no work".
- The desktop answers with no events in the span: known, no activity (the same as a phone DB with none).
- The phone DB set and unreadable is unknown as before, even with the desktop live.

Overlapping phone and desktop work time counts once. A phone app in the foreground between two desktop work
rows reads as a switch away, as it would on one device.

## Doctor row

`limitless-doctor` ends with a `desktop AW` row, words only, never the address, a path, an app or a title:
`off` (not set), `live` (active app time in the last day, with its age in words), `stale` (it answers with
none in the last day) or `missing` with the reason starting "unreachable:". The row's kind is `source`, so
`--strict` does not count it.

## A synthetic run

`python3 -I scripts/desktop_aw_example.py`: a fake fetch serves made-up buckets the way aw-server does,
with a planted window title in every window event. Nothing touches the network.

```text
$ aw_desktop.read_events(url, day_start, day_end, fetch=<synthetic server>)
state: live
  9-10.5h editor
  10.5-10.6h scroller
  10.6-12h editor
  13-14h editor
  14-15h terminal
planted title anywhere in the result: False
$ flow words with the desktop as the only source (no phone DB set)
flow ledger: two long blocks, one with a feed leak
flow metrics: work stayed in long blocks
flow metrics, desktop asleep: unknown: the desktop ActivityWatch server did not answer
$ limitless-doctor (the desktop AW row only)
desktop AW: off: desktop ActivityWatch is not set (desktop_aw_url or desktop_aw_export)
desktop AW: live: active app time about an hour ago
desktop AW: stale: it answers, with no active app time in the last day
desktop AW: missing: unreachable: the desktop ActivityWatch server did not answer
```

No score, no target and no clock-time rule: the words describe observed app activity, not attention or
output. Stdlib only, Python 3.9+.
