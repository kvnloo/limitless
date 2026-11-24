# Sleep coverage: on how many nights did the wearable record sleep?

North-star row five: the foundation measured honestly, with wearable sleep on at least four nights in five and
every value labelled. `limitless/sleep_coverage.py` measures that from the files the plugin already reads, so
nobody has to count nights by hand. It is read-only: it reads the wearable sleep file and the phone's screen
events and never writes, restarts, starts or sends anything. It is the same shape as the
[uptime audit](uptime-audit.md) and the [delivery audit](delivery-audit.md): a pure function over nights, T0
counts kept in the dict, one digit-free label, a read-only tool and CLI, and a doctor row.

## The two sources and the fields relied on

- The wearable sleep file, config `sleep_file` (written by `limitless-noop-export` or `limitless-ow-export`,
  [noop-export.md](noop-export.md), [open-wearables.md](open-wearables.md)), one row per night:
  `{"night": "YYYY-MM-DD", "asleep_s": <seconds>, "source": "<name>"}`. A row counts exactly when
  `StateReader.sleep_rows` would keep it (a valid night, `asleep_s` a whole number above zero, a non-empty
  `source`), the same rows `limitless_sleep` reads.
- The phone estimate: the quiet spans between the person's own phone actions (screen events and the
  ActivityWatch DB's unlocks, `sleep.screen_gaps`), the same proxy `limitless_sleep` shows beside the wearable.
  A night's estimate is the longest quiet span that starts in the evening half of its date.

A night is named by the evening it began, in this machine's zone (the tool and the CLI) or the zone the caller
passes.

## Demo rows never count

Before any night is read, every sleep file row in the window that `mock_guard` calls a demo or sample row is
dropped and only counted: a demo device id or name (`deviceId`, `device`, `id` or `name`, e.g. a `demo-` id or a
name ending in `(demo)`), an Open Wearables `source` object with a demo device, a seed user's `first_name`, a
`source` text carrying one of those marks, or anything matching config `mock_device_patterns`
([mock-guard.md](mock-guard.md)). When any was dropped, the label ends with "some demo rows were left out".

## Rules

- Window: the last `sleep_coverage_days` local nights before today (config, a whole number, default 28).
- Per night: wearable when a valid, non-demo wearable row names it; phone estimate only when the phone has a
  quiet span that evening and the wearable has none; unknown when neither says anything. The phone estimate
  never counts as wearable: a quiet phone is not a sleep measure. A night with no data is unknown, not zero.
- Goal (the uptime audit's rule): the wearable share is over the whole window, so an unknown night counts
  against the goal, never for it. "met" when the wearable nights reach `sleep_coverage_target` of the window
  (config, above zero and at most one, default 0.8, the scorecard's bar), rounded up; "not met" when even every
  unknown night being wearable would not reach it; else "unknown".
- Fewer than a week of known nights (wearable or phone estimate) is "unknown", with a reason.

## Words

One T1 label, no digit: the wearable nights, then the phone-estimate-only nights and the nights with no data
when there are any, each as every night, most nights (more than half), about half the nights, some nights or
few nights, then the goal: "wearable sleep on few nights, phone estimate on most nights; wearable goal not met".
No wearable night at all is "no wearable sleep". No score, no advice and no clock time.

## Tool, CLI and doctor row

- `limitless_sleep_coverage`: an envelope whose value is `{label}` with the T1 label beside it; modality
  measured when any wearable night counts, else proxy; aged like `limitless_sleep` (the newest phone span's
  end, or the local midnight after the newest wearable night). The counts (`window_nights`, `wearable_nights`,
  `proxy_only_nights`, `unknown_nights`, `known_nights`, `wearable_share`, `target`, `goal`, `demo_rows`) are
  T0 and appear only under the raw opt-in (`LIMITLESS_RAW_IN_PROMPT=1`). No `sleep_file` set, a missing or
  unreadable file, no night with any data, or fewer than a week of known nights is `value: null` with a reason
  and the label "unknown"; a reason never echoes a path.
- `bin/limitless-sleep-coverage [--json]`: prints the words, or "unknown: <why>"; `--json` prints the counts.
  Read-only, exit 0.
- `limitless-doctor` has a `sleep coverage` row (kind source, so `--strict` never counts it) just before the two
  wearable export rows that write the sleep file: live when the wearable goal was met, stale when it was not,
  missing when unknown, off when no `sleep_file` is set; the reason is the words, never a count
  ([doctor.md](doctor.md)).

This replaces reading row five of the scorecard by hand; the scorecard itself stays hand-kept, and nothing here
ever marks a row.

## Example

The real output of `python3 -I scripts/sleep_coverage_example.py` (synthetic rows, a fixed clock, UTC):

```text
# limitless_sleep_coverage, no raw opt-in (default window: four weeks, target four nights in five)
{"value": {"label": "wearable sleep on some nights, phone estimate on most nights, no sleep data on few nights; wearable goal not met; some demo rows were left out"}, "modality": "measured", "age_h": 2.0, "evidence_tier": "direct"}
{"label": "wearable sleep on some nights, phone estimate on most nights, no sleep data on few nights; wearable goal not met; some demo rows were left out", "tier": "T1", "modality": "measured"}

# the same with the raw opt-in: T0 counts
{"window_nights": 28, "wearable_nights": 10, "proxy_only_nights": 15, "unknown_nights": 3, "known_nights": 25, "wearable_share": 0.35714285714285715, "target": 0.8, "goal": "not met", "demo_rows": 5}

# config sleep_coverage_days: 7
wearable sleep on every night; wearable goal met

# config sleep_coverage_days: 14, sleep_coverage_target: 0.5
wearable sleep on most nights, phone estimate on some nights; wearable goal met; some demo rows were left out

# sleep_file set, but the file is not there: unknown, never zero, and the reason names no path
{"value": null, "modality": "measured", "age_h": null, "evidence_tier": "none", "reason": "the wearable sleep file is missing or cannot be read"}

# no sleep_file set
no wearable sleep file: set "sleep_file" in config.json

# sleep.jsonl is unchanged: 15 lines
```
