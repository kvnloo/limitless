# Open Wearables: wearable sleep from a self-hosted Open Wearables server

The rule is that health data lives in Open Wearables, not in a second store. `limitless_sleep`, its regularity
and the week review read wearable nights from config `sleep_file`; until now only the NOOP export
([noop-export.md](noop-export.md)) wrote that file. `bin/limitless-ow-export` makes an
[Open Wearables](https://github.com/the-momentum/open-wearables) server a second, equal source for the same file,
in the same row shape, so every reader of the sleep file works unchanged. It wraps the server's REST API; it does
not copy its store. Off by default.

## The API it reads

Read from the public repo github.com/the-momentum/open-wearables (MIT) at commit
e7918575f87b825e12d367445eb417fbcd2588b2:

- `docs/api-reference/introduction.mdx`: every endpoint is under `/api/v1`, and the API key goes in the
  `X-Open-Wearables-API-Key` header ("Do not use Bearer token format").
- `docs/api-reference/guides/quick-integration.mdx` ("Sleep Sessions") and `docs/openapi.json`
  (`GET /api/v1/users/{user_id}/events/sleep`, "List Sleep Sessions"): required `start_date` and `end_date`
  (ISO-8601 or a date; a date-only end covers that whole day), optional `cursor` and `limit` (1 to 1000).
- `backend/app/api/routes/v1/events.py` (`list_sleep_sessions`) and
  `backend/app/schemas/responses/activity/events.py` (`SleepSession`): the answer is
  `{"data": [SleepSession, ...], "pagination": {"next_cursor", "has_more", ...}, "metadata": {...}}`; a session
  has `start_time`, `end_time`, `sleep_duration_seconds` (time asleep, awake time excluded), `stages`
  (`light_minutes`, `deep_minutes`, `rem_minutes`, `awake_minutes`), `is_nap` and `source.device_type`.

The tool asks for the last thirty days (`start_date` thirty days before today, `end_date` tomorrow) and follows
`next_cursor` while `has_more` is true, at most fifty pages. Nothing else of the API is used.

## Settings

- `open_wearables_export` in config.json: `off` (the default, and any other value), `dry_run` or `write`.
- `open_wearables_url`: the server's base address, `http` or `https` (a trailing `/api/v1` is fine).
- `open_wearables_user`: the Open Wearables user id whose sleep is read.
- The API key: only from the environment variable `LIMITLESS_OW_KEY`, never from config.json (a key there is
  ignored), and it is never printed, logged, written to the mark or put in a reason. It is sent only in the
  `X-Open-Wearables-API-Key` header, never in the URL.

## The rows

- **One sleep row per night**, noop_export's shape: `{"night", "asleep_s", "source": "open_wearables", "start",
  "end"}`, the fields `StateReader.sleep_rows` reads. `night` is the evening the sleep began in the local zone
  (the `sleep.py` rule noop_export uses: a sleep that began after midnight belongs to the date before); `start`
  and `end` are the session's times in UTC.
- **Time asleep** is `sleep_duration_seconds`, else light + deep + REM minutes from `stages`; with neither there
  is no row. Time in bed and the session's span are never taken as sleep: never a guess.
- **Skipped and counted:** naps (`is_nap`), sessions from a phone, tablet, scale or smart display
  (`source.device_type`), sessions with no asleep time, and spans that are not a night (end before start, over a
  day, unreadable times). Of several sessions in one night, the one with the most sleep is the night.
- **Demo rows never count** ([mock-guard.md](mock-guard.md)): a session whose `source.device` or
  `source.device_id` is a demo device, or matches config `mock_device_patterns`, is dropped. With sessions to
  read, the user record (`GET /api/v1/users/{user_id}`) is read once: a seed user's sessions are all demo
  rows. An unreadable user record changes nothing. Only demo rows is "no wearable data", a failed run.
- **Privacy:** the rows carry only those fields: no provider, device, user id or session id. The output is counts
  in words: never a path, the URL, the user, the key or a reading.

## Which wins

One night from both sources keeps one row, and the NOOP row wins: a night that a row of another source (`noop`,
or any other source already in the file) holds keeps only that row. `--write` does not add an `open_wearables` row
for it, and drops an `open_wearables` row an earlier run wrote once another source has written that night. Open
Wearables fills the nights nobody else has. The NOOP export reads the strap directly, so its night is first; the
readers already take the first row of a night (`sleep.py`), and this keeps the file to one row per night.

## Running it

- `bin/limitless-ow-export`: a dry run. It prints the counts in words and writes nothing.
- `bin/limitless-ow-export --write`, with `open_wearables_export` set to `write`: merges the rows into
  `sleep_file` with noop_export's merge (by night and source; every other row and line is kept) and its atomic
  write (a temp file in the same directory, then a rename) with mode `0600`. A rerun with nothing new prints
  `unchanged` and leaves the bytes as they were. With `dry_run` set, `--write` is still a dry run.
- Errors (no URL, no user, no key, a refused key, an HTTP error, a timeout, an unreachable server, an answer
  that is not the sleep list) are one plain line on stderr, exit 1, and nothing is written. Bad arguments exit 2.
  Off exits 0.
- Each run that is not off records `open-wearables.json` in the state dir (atomic, 0600): when it ran, the mode,
  done or failed and the line it said. The doctor's `export Open Wearables` row reads it, never the server: `off`,
  `live` (the last run read the server within a day), or `stale` with `failing:` and the reason
  ([doctor.md](doctor.md)).
- No job, no tool and no push: it runs when the operator runs it. Never a clock time, no advice.

## Synthetic example

`python3 -I scripts/ow_export_example.py` (the made-up pages in `tests/fixtures/open_wearables`, served by an
injected http callable, no network; the sleep file already holds one NOOP night; UTC as the local zone; real
output):

```text
$ limitless-ow-export   (open_wearables_export=unset)
the Open Wearables export is off (config open_wearables_export)
  (exit 0)

$ limitless-ow-export   (open_wearables_export=write)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa/events/sleep (header X-Open-Wearables-API-Key)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa/events/sleep (cursor, header X-Open-Wearables-API-Key)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa (header X-Open-Wearables-API-Key)
dry run: three nights of wearable sleep from Open Wearables; skipped one nap, one session not from a wearable, one session with no asleep time; nothing written (run with --write to write them)
  (exit 0)

$ limitless-ow-export --write   (open_wearables_export=write)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa/events/sleep (header X-Open-Wearables-API-Key)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa/events/sleep (cursor, header X-Open-Wearables-API-Key)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa (header X-Open-Wearables-API-Key)
found three nights of wearable sleep from Open Wearables; skipped one nap, one session not from a wearable, one session with no asleep time
sleep file: written, two nights new or changed; one night kept from another source
  (exit 0)

$ limitless-ow-export --write   (open_wearables_export=write)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa/events/sleep (header X-Open-Wearables-API-Key)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa/events/sleep (cursor, header X-Open-Wearables-API-Key)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa (header X-Open-Wearables-API-Key)
found three nights of wearable sleep from Open Wearables; skipped one nap, one session not from a wearable, one session with no asleep time
sleep file: unchanged; one night kept from another source
  (exit 0)

$ limitless-ow-export --write   (open_wearables_export=write, server refuses the key)
  GET /api/v1/users/00000000-0000-4000-8000-0000000000aa/events/sleep (header X-Open-Wearables-API-Key)
the Open Wearables server refused the API key
  (exit 1)

sleep.jsonl (3 rows, mode 0o600):
{"night": "2030-01-01", "asleep_s": 24600, "source": "noop", "start": "2030-01-01T23:05:00Z", "end": "2030-01-02T06:55:00Z"}
{"night": "2030-01-02", "asleep_s": 23400, "source": "open_wearables", "start": "2030-01-03T01:30:00Z", "end": "2030-01-03T08:30:00Z"}
{"night": "2030-01-06", "asleep_s": 26400, "source": "open_wearables", "start": "2030-01-06T22:30:00Z", "end": "2030-01-07T06:30:00Z"}

$ limitless-doctor | grep Open
export Open Wearables: stale: failing: write mode: ran about an hour ago: the Open Wearables server refused the API key
limitless_sleep: modality proxy; sleep: wearable on some nights; phone proxy has no night to compare
files in the state dir: open-wearables.json, sleep.jsonl
```
