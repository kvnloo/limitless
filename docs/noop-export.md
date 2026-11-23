# NOOP export: wearable sleep and pre-sleep heart rate from the NOOP app's database

`limitless_sleep` reads wearable nights from config `sleep_file` and `limitless_presleep_hr` reads config
`presleep_hr_file`, but nothing wrote those files, so the sleep tool only had the phone proxy.
`bin/limitless-noop-export` writes them from a copy of the database of [NOOP](https://github.com/ryanbr/noop), the
open-source on-device app that reads the strap or ring directly (no vendor app, no cloud). The operator's sync
already copies that database; this tool only reads the copy.

## What it reads

Config `noop_db`: the path of the copy (relative paths are in the state dir; none by default, and unset means
"nothing to export"). The file is opened through a `file:...?mode=ro&immutable=1` URI, as the Anki reader does:
nothing is written, created or locked beside it, and a test proves its bytes and mtime stay the same.

Tables and columns, from NOOP's public Android Room entities:

- `sleepSession` (`deviceId`, `startTs`, `endTs`, `efficiency`, `stagesJSON`, optional `startTsAdjusted`):
  `android/app/src/main/java/com/noop/data/Entities.kt` (`SleepSession`). Times are unix seconds.
- `hrSample` (`deviceId`, `ts`, `bpm`): same file (`HrSample`).
- `pairedDevice` (`id`, `sourceKind`): `android/app/src/main/java/com/noop/data/PairedDevice.kt`
  (`PairedDeviceRow`, `SourceKind`).
- `dismissedSleep` (`deviceId`, `startTs`), optional: sessions the person dismissed in the app are skipped.

A missing table or column is one plain line, `not a NOOP database this exporter knows: no table hrSample` (or
`no column sleepSession.endTs`), exit 0, and nothing is written: never a guess from a schema the tool does not
know. A missing or unreadable file is one plain line too.

## The rows

- **Wearable only.** A session counts only when its `deviceId` is a paired device whose `sourceKind` is read
  straight off a strap or ring (`liveBLE`, `historyBLE`, `oura`, `huami`). The phone's health-store bucket, a
  file or cloud import, a fitness machine and an activity file are not the wearable and are skipped. A session
  whose `deviceId` has no `pairedDevice` row (a re-pair can orphan a strap's history, NOOP #1193) counts when
  the id is in NOOP's strap namespace (`whoop-...`, `oura-...`, or the legacy `my-whoop` seed); a paired row's
  `sourceKind` always wins over the id.
- **One sleep row per night** (`sleep_file`): `{"night", "asleep_s", "source": "noop", "start", "end"}`, the
  shape `StateReader.sleep_rows` reads. `night` is the evening the night began (the rule `sleep.py` uses: a sleep
  that began after midnight belongs to the date before). Of several wearable sessions in one night, the one with
  the most sleep is the night, so an evening nap never stands for it. `asleep_s` is light + deep + REM from
  `stagesJSON` (NOOP's computed `[{start, end, stage}]` spans or imported minute totals); with no stages, the
  in-bed span times `efficiency`; with neither, no row: time in bed is not time asleep, and the tool never
  guesses. `start` is the onset (the hand-set onset when the person corrected it), `end` the wake, both UTC.
- **One pre-sleep heart-rate row per night** (`presleep_hr_file`): `{"night", "bpm", "modality": "measured"}`,
  the shape `StateReader.presleep_hr_rows` reads. `bpm` is the mean of the sleeping wearable's own `hrSample`
  rows in the half hour right before that night's onset, rounded to a tenth. The window is anchored on the onset
  event, never a clock time. Samples outside `presleep_hr`'s plausible range are not counted, and under ten
  samples there is no row for that night: never a guess, never zero. These are the window and the minimum NOOP's
  own pre-sleep reading uses (`PreSleepHeartRateFeedback`).
- **Privacy.** The rows carry only those fields: no device name, model, serial, MAC, nickname, user id or free
  text from the app, and `source` is always `noop`. The printed lines carry counts in words and never a path, a
  device or a reading. A test plants a name, a device name and serial-like strings in the database and checks
  that none of them reaches the files or the output.

## Running it

- `bin/limitless-noop-export`: a dry run. It prints the counts in words and writes nothing.
- `bin/limitless-noop-export --write`: merges the rows into `sleep_file` and `presleep_hr_file` (both from config,
  relative to the state dir; never hard-coded). Each file is written atomically (a temp file in the same
  directory, then a rename) with mode `0600`. The merge is by night: a row of ours replaces the row with the
  same night and source (or modality), and every other row (older nights no longer in the copy, another
  exporter's rows, a phone row) is kept. Rows are sorted, so a rerun with nothing new prints `unchanged` and
  leaves the file's bytes and mtime as they were. An output that is not configured is named and skipped.
- Exit 0 when done or when there is nothing to export, 1 when a file cannot be written (one line on stderr), 2
  for bad arguments.

Run it after each sync of the NOOP copy: by hand, or as the event job below, which `limitless-jobs` runs on
the sync's own "copied" event.

## Synthetic example

`python3 -I scripts/noop_export_example.py` (a made-up database in a temp dir, UTC as the local zone; real
output). Sixteen wearable nights, one with too little heart rate before sleep, plus an afternoon nap, a phone
session and a file import:

```text
$ limitless-noop-export   (exit 0)
dry run: sixteen nights of wearable sleep and fifteen nights of pre-sleep heart rate in the NOOP database; skipped two sessions not from a wearable, one night with too few heart-rate samples; nothing written (run with --write to write them)

$ limitless-noop-export --write   (exit 0)
found sixteen nights of wearable sleep and fifteen nights of pre-sleep heart rate in the NOOP database; skipped two sessions not from a wearable, one night with too few heart-rate samples
sleep file: written, sixteen nights new or changed
pre-sleep heart-rate file: written, fifteen nights new or changed

$ limitless-noop-export --write   (exit 0)
found sixteen nights of wearable sleep and fifteen nights of pre-sleep heart rate in the NOOP database; skipped two sessions not from a wearable, one night with too few heart-rate samples
sleep file: unchanged
pre-sleep heart-rate file: unchanged

last three rows of sleep.jsonl (16 rows, mode 0o600):
{"night": "2030-01-25", "asleep_s": 27000, "source": "noop", "start": "2030-01-25T23:15:00Z", "end": "2030-01-26T07:15:00Z"}
{"night": "2030-01-26", "asleep_s": 27600, "source": "noop", "start": "2030-01-26T22:30:00Z", "end": "2030-01-27T06:30:00Z"}
{"night": "2030-01-27", "asleep_s": 25200, "source": "noop", "start": "2030-01-27T23:45:00Z", "end": "2030-01-28T07:45:00Z"}

last three rows of presleep-hr.jsonl (15 rows, mode 0o600):
{"night": "2030-01-25", "bpm": 59.0, "modality": "measured"}
{"night": "2030-01-26", "bpm": 60.0, "modality": "measured"}
{"night": "2030-01-27", "bpm": 61.0, "modality": "measured"}

limitless_sleep: modality measured; sleep: wearable on most nights; phone proxy has no night to compare; wearable: sleep times steady
limitless_presleep_hr: modality measured; pre-sleep heart rate about usual (wearable)
files in the state dir: noop-copy.db, presleep-hr.jsonl, sleep.jsonl
```

Observation only: no advice, no target, no score, no clock-time rule, no drug, supplement or dosing note. Nothing
here sends, starts a job or touches the NOOP app; the tools still read the files the same way, so a stale copy
still reads as stale.

## As an event job

`limitless-jobs --send` (`jobs_runner.run_once`) can run the export itself, on an event rather than by hand: one
job, `jobs.NOOP_EXPORT` ("NOOP export"), woken by `noop_copy`, a sync that copied the NOOP database. It reuses the
runner's pass and the way the other event jobs decide "due" and record that they ran; there is no second
scheduler, no timer of its own and no clock time.

- **The event.** The sync appends one row per run to `runs.jsonl`. A row says it copied the NOOP database in its
  `"noop"` field: `true`, `"copied"` or `"fresh"`, or an object with `"copied": true` (or `"fresh": true`). A row
  with `"ok": false` never counts (its copy may be torn), and neither does a digest-style `{"available": ...}`.
  The job is due when the newest row is such a row, it is not in the future, and it is newer than the row the
  last export acted on. One row is one run: polled again, the same row is a `drop` ("already ran after this
  sync"); a later sync that did not copy the database is `not_triggered`.
- **Config `noop_export`.** `off` (the default, and any other value): never due, and `limitless-jobs` prints no
  line for it. `dry_run`: calls `noop_export.main` with no arguments, so it reads the copy and records the counts
  only; no sleep or pre-sleep file is written. `write`: calls it with `--write`, the same merge and atomic 0600
  write as the command, so a rerun on an unchanged copy is `unchanged` and byte-identical. The call is
  in-process; `limitless-jobs` without `--send` is a dry run of the runner, which gives the verdict and runs
  nothing.
- **Plain reasons, never a loop.** No `noop_db`, no file at that path or a schema the exporter does not know is the
  command's own plain line, recorded as "nothing to export" for that row; an output (`sleep_file`,
  `presleep_hr_file`) that is not configured is named and skipped while the other is written. Either way the row
  is marked, so the same copy is not retried every poll; the next sync that copies the database tries again.
- **The mark `noop-export.json`** (in the state dir, atomic, 0600): `row_at` (epoch seconds of the `runs.jsonl` row
  it acted on), `ran_at` (epoch seconds of the run), `mode`, `outcome` (`done`, `nothing to export`, `a file was
  not written`, `failed`) and `said`, the command's lines, which are counts in words. Nothing else: no path, no
  reading, no device id, and no digit outside the two epoch values.
- **What it never does.** It never sends or pushes anything (no decision window, quiet or send gate is involved,
  and nothing is appended to `jobs-sent.jsonl`), so it also runs while you sleep; and it
  never restarts, kills or starts a process.
- **Schedule card.** With `noop_export` on, `limitless_schedule` and the host registration add one #158289-shaped
  card (`schedule_cards.noop_export_card`, sender `local`, budget zero) on the trigger "after a sync that copied
  the NOOP database": no clock time, no cron string.
- **Doctor.** `limitless-doctor` ends with one `job NOOP export` row: `off` by config; `stale` while a sync copied
  the database and the export has not run after it, when no sync has copied it yet, or when the last run found
  nothing to export (with that reason) or could not write; else `live`, with the mode and the run's age in words.
  `--strict` never counts this row.

### Synthetic example

`python3 -I scripts/noop_export_job_example.py` (a made-up database and made-up `runs.jsonl` rows in a temp dir,
UTC as the local zone; real output):

```text
# config noop_export unset (off)
runs.jsonl += {"at": "2030-01-06T03:00:00Z", "job": "sync", "ok": true, "noop": {"copied": true}}
$ limitless-jobs --send   (the NOOP export's line)
(no NOOP export line)

# config noop_export "dry_run"
$ limitless-jobs --send   (the NOOP export's line)
NOOP export: run: a sync copied the NOOP database; ran (done): dry run: five nights of wearable sleep and five nights of pre-sleep heart rate in the NOOP database; nothing written (config noop_export "write" writes them)

# config noop_export "write"; the next sync copied the NOOP database again
runs.jsonl += {"at": "2030-01-06T06:00:00Z", "job": "sync", "ok": true, "noop": {"copied": true}}
$ limitless-jobs --send   (the NOOP export's line)
NOOP export: run: a sync copied the NOOP database; ran (done): found five nights of wearable sleep and five nights of pre-sleep heart rate in the NOOP database; sleep file: written, five nights new or changed; pre-sleep heart-rate file: written, five nights new or changed

# the same sync row, polled again
$ limitless-jobs --send   (the NOOP export's line)
NOOP export: drop: already ran after this sync of the NOOP database

# a sync that did not copy the NOOP database, then one that did
runs.jsonl += {"at": "2030-01-06T07:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the NOOP export's line)
NOOP export: not_triggered: the last sync run did not copy the NOOP database

runs.jsonl += {"at": "2030-01-06T08:00:00Z", "job": "sync", "ok": true, "noop": {"copied": true}}
$ limitless-jobs --send   (the NOOP export's line)
NOOP export: run: a sync copied the NOOP database; ran (done): found five nights of wearable sleep and five nights of pre-sleep heart rate in the NOOP database; sleep file: unchanged; pre-sleep heart-rate file: unchanged

sleep.jsonl byte-identical after the rerun: True
noop-export.json (mode 0o600):
{"mode": "write", "outcome": "done", "ran_at": 1893916860.0, "row_at": 1893916800.0, "said": ["found five nights of wearable sleep and five nights of pre-sleep heart rate in the NOOP database", "sleep file: unchanged", "pre-sleep heart-rate file: unchanged"]}

$ limitless-doctor   (the job row)
job NOOP export: live: write mode: ran under an hour ago after a sync that copied the NOOP database: done

schedule card:
Schedule "NOOP export" (after a sync that copied the NOOP database, at most once; asleep or awake: it sends nothing, so no window holds it): ends at the next sync that copies the NOOP database; nothing is sent; it reads the NOOP copy and, in write mode, merges the sleep file and the pre-sleep heart-rate file
files in the state dir: noop-copy.db, noop-export.json, presleep-hr.jsonl, runs.jsonl, sleep.jsonl
```
