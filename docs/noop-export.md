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

Run it after each sync of the NOOP copy, for example from the same timer.

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
