# Mock guard: demo, mock and sample wearable rows are never live

Health apps ship demo devices and sample data. `limitless/mock_guard.py` tells those rows apart from real ones,
and every wearable read path drops them before anything is counted or written. A demo row never becomes live
evidence, a wearable night or heart-rate words.

## The markers (cited, never guessed)

Only markers the source apps really write are used:

- **NOOP** ([github.com/ryanbr/noop](https://github.com/ryanbr/noop), read at `2a1de76`). Its demo seeders fill
  an empty store with synthetic data.
  - The Android `DemoSeeder` pairs a demo strap whose id starts with `demo-`
    (`android/app/src/main/java/com/noop/data/DemoSeeder.kt:70`).
  - The Apple twin pairs one whose id ends in `-demo` (`Strand/Data/AppleDemoSeeder.swift:55`).
  - Both write the demo dataset under the ordinary legacy strap id and mark it only through that id's `device`
    table name, which ends in `(demo)` (`DemoSeeder.kt:93`, `AppleDemoSeeder.swift:67`). The export reads
    `device.name` for this alone; a database without that table reads as before.
  - The Android demo flavour (`android/app/build.gradle.kts:111-116`, `ENABLE_DEMO`) leaves no mark in the
    database itself, so it is not a marker.
- **Open Wearables** ([github.com/the-momentum/open-wearables](https://github.com/the-momentum/open-wearables),
  read at `e791857`). The seed generator marks a seed user's `first_name` with the prefix `[SEED:`
  (`backend/app/services/seed_data/service.py:155`). That is the one seed marker the API returns
  (`UserRead.first_name`, `backend/app/schemas/model_crud/user_management/user.py:117`). The `is_seed` column
  (`backend/app/models/user.py:25`) is not in the API. A seed user's sleep sessions carry the same `source` as
  real ones (`service.py:48`), so there is no session-level marker. The reader asks for the user record once
  (`GET /api/v1/users/{user_id}`) when there are sessions; an unreadable record changes nothing.
- **Config `mock_device_patterns`**: a list of glob patterns (default empty) for a host's own simulator or sample
  device ids, device names, Open Wearables `source.device` / `source.device_id`, or inputs.json input names.
  Matching is case-insensitive.

## Where it applies

- **NOOP export** (`limitless-noop-export` and the `noop_export` job): demo sessions are dropped before the night
  is picked, so a demo night never beats a real one and a demo strap's heart-rate samples are never read. Mixed
  input says `some demo rows were left out (N sessions from a demo or sample device)` in words. A database whose
  sessions are all demo rows is `no wearable data: only demo or sample rows`: nothing is written, the job records
  `nothing to export` and the doctor's `job NOOP export` row is `stale`, never `live`. A live row after a mixed
  run ends `; some demo rows were left out`.
- **Open Wearables export** (`limitless-ow-export`): the same, per session's source device, and every session of
  a seed user. Only demo rows is a failed run (exit one, nothing written), so the doctor's
  `export Open Wearables` row is `stale`.
- **limitless_status, the doctor's input rows and the breathing line's heart words**: an inputs.json name with a
  demo mark or matching a pattern is state `demo` (no age, listed under `unknown`), never `recording`; its doctor
  row is `missing`. A configured `wearable_inputs` name that is a demo device is ignored, so "with live heart
  data" never comes from it.
- The sleep and pre-sleep heart-rate file readers (`StateReader.sleep_rows`, `presleep_hr_rows`) read no device
  id, so the guard sits at the exporters that write those files.

All-real input reads, counts and writes exactly as before. All output is in words, with no digits.

## A synthetic run

`python3 -I scripts/mock_guard_example.py` (made-up rows in a temporary state dir; nothing is sent):

```text
$ limitless-noop-export   (two real nights; two from a demo- id, one the demo device name marks, one matching mock_device_patterns)
dry run: two nights of wearable sleep and two nights of pre-sleep heart rate in the NOOP database; some demo rows were left out (four sessions from a demo or sample device); nothing written (run with --write to write them)
  (exit 0)

$ limitless-noop-export --write   (only demo rows)
no wearable data: only demo or sample rows (some demo rows were left out)
  (exit 0)

sleep file written: False

$ limitless-ow-export --write   (the user is an Open Wearables seed user)
no wearable data: only demo or sample rows (some demo rows were left out)
  (exit 1)

limitless_status inputs:
  demo-band-a: demo
  sim-band-c: demo
  wearable: recording
  unknown: demo-band-a, sim-band-c

$ limitless-doctor | grep -E 'input|export'
input demo-band-a: missing: a demo or sample device: demo rows never count as live
input sim-band-c: missing: a demo or sample device: demo rows never count as live
input wearable: live: recording: updated within the last day
export Open Wearables: stale: failing: write mode: ran about an hour ago: no wearable data: only demo or sample rows (some demo rows were left out)
```
