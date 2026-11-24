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
message or starts a job. Synthetic test files only (tests/test_fit_ride.py builds them with a tiny writer).
