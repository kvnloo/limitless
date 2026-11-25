# CAROL bike rides from FIT files

A CAROL bike rider can export each past ride from the CAROL web dashboard (Rides, the ride's menu,
"Download .FIT"): one Garmin FIT file per ride, no bulk or CSV export. `bin/limitless-import-fit` turns each
file into one row of the rides file the plugin already reads ([rides.md](rides.md)); there is no second store.

```
bin/limitless-import-fit ride-a.fit ride-b.fit          # dry run: what would be added, in words
bin/limitless-import-fit --write ride-a.fit ride-b.fit  # append the new rides
bin/limitless-import-fit --json ride-a.fit              # the whole result as JSON, numbers included
```

- **Where it writes**: the configured rides file only (config `rides_file`, a relative path is in the state
  dir). Not set: a dry run still reads the files, and `--write` says `no rides file set` and exits 1.
- **Row**: `{"start": ..., "duration_s": ..., "kind": "ride", "source": "carol-fit"}`. `ride` is in the
  default `ride_kinds`, so `StateReader.ride_rows()` and the weekly rides line count it with no config change.
- **Start**: the session's start time, in UTC with `Z`, unless the file's activity message carries a local
  timestamp; then the start keeps that offset (rounded to a quarter hour), because a ride's day is the date
  of its start in its own offset.
- **Duration**: the session's total elapsed time, else its total timer time, in whole seconds.
- **Dedupe**: a ride whose start instant is already in the file with source `carol-fit` (written in any
  offset) is `already in the rides file` and is not appended, so importing the same file twice adds nothing.
- **Words**: one line per file (`would add one ride`, `added one ride`, or why not: `not a FIT file`, `the FIT
  file is cut short`, `the FIT file check does not match, the file is damaged`, `no ride summary in the file`,
  `not a bike ride`, `the ride has no duration`, ...), then the total, e.g. `added two rides`. No number is
  printed except with `--json`. Exit 2 on a usage error.

## Drop folder

Exports usually come in batches. Instead of running the importer per file, drop the files into one folder and let
`limitless-jobs` import them as one more ingest, the same shape as the reply ingests:

```json
{"rides_file": "rides.jsonl", "fit_drop_dir": "fit-drop", "fit_ingest": "dry_run"}
```

- **Config**: `fit_drop_dir` names the folder (a relative path is in the state dir). `fit_ingest` is `off` (the
  default: no line, nothing read), `dry_run` (reads the files and says what it would add; no ride is written) or
  `write` (appends the new rides to the rides file).
- **When**: once per new sync row in `runs.jsonl`, never on a clock time; the timer's `limitless-jobs --ingest`
  pass (or `--send`) runs it, a plain dry run of `limitless-jobs` only shows its verdict. Its line is `FIT import`.
- **Which files**: `*.fit` / `*.FIT` directly in the folder: no subfolders, no symlinks (never followed, in or out
  of the folder), no dotfiles; oldest modification time first, at most twenty files per pass (files sharing one
  modification time are never split across passes). The rest wait for the next pass, which goes on after the newest
  file a write pass read. A dry run never moves that place, so it always previews the next files.
- **Safe to re-run**: each file goes through the same `fit_ride.run` as the importer, so a ride whose start instant
  is already in the rides file (imported by hand, or twice in the folder) is a duplicate and is not appended. A file
  copied in keeping a modification time older than the newest file already read is not picked up: import it with
  `bin/limitless-import-fit --write`.
- **Never**: a source file is never moved, renamed, deleted or rewritten; nothing is sent (no `kevin-push` call).
- **Mark**: `fit-ingest.json` in the state dir (atomic, 0600): epoch seconds (`row_at`, `ran_at`, `read_to`) and
  words only, the mode and what the last pass did, e.g. `added two rides`, `nothing new`, `would add one ride`,
  `skipped one file: not a bike ride`, `more files wait for the next pass`. Never a file name, a path or a number
  from a ride.
- **Brief line**: after a `write` pass added rides, the next delivered wake brief says so once, in words:
  `Imported two bike rides from your CAROL exports.` (capped at `more than twenty`; no digit). The pass records
  `added_at` (epoch seconds) and `added` (words, e.g. `two rides`, summed over passes not told yet) in the mark;
  `fit_ingest_job.brief_fit_rides` reads only that, through the tier audit gate (hook `brief:fit_rides`), and
  `bin/limitless-brief send` marks it told in `fit-rides-told.json` (`told`, `told_at`: epochs only, 0600) only
  after a real delivery, so a held or failed send says it next time. A dry run, config `off`, or rides imported by
  hand with `bin/limitless-import-fit` never make the line.
- **Doctor**: the `job FIT import` row says `off`, or `dry run` / `write` with the last pass in words; `missing` when
  the folder is set but does not exist, `stale` with no folder set or before its first pass after a sync.
- **Schedule card**: `fit_ingest`, on the `sync` event, sender `local`, budget zero
  ([schedule-cards.md](schedule-cards.md)).

## What is read

`limitless/fit_ride.py`, stdlib only, reads just enough of the FIT format for one row: the file header (12 or
14 bytes, the `.FIT` signature, the data size), the header CRC when present and the file CRC, definition and
data messages (local message types, little or big endian, compressed-timestamp headers, developer fields
skipped by size), the first `session` message (start time, total elapsed or timer time, sport: cycling only)
and the `activity` message's local timestamp. It never raises on bad bytes: a damaged file is a reason.

## What is ignored

Everything else stays unread in the file: per-second power, heart rate and cadence samples, laps, calories,
device and file-creator details. Those numbers are tier T0 and never enter a prompt; the importer copies only
the start and the duration into the rides file, and the rides tool turns the week into digit-free words.

## Never

It never reads the network, deletes or rewrites anything (append only, one flocked write, mode 0600), sends a
message or starts a job (the drop folder's job above is run by `limitless-jobs`, and sends nothing). Synthetic test
files only (tests/test_fit_ride.py builds them with a tiny writer).
