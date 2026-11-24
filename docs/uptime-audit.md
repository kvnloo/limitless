# Uptime audit: were the inputs fresh, day by day?

North-star row one: every input fresh within a day on nearly every day. `limitless/uptime_audit.py` measures
that from the sync's own run log, `runs.jsonl` in the state dir (the file the doctor's last-sync row already
reads), so nobody has to read the log by hand. It is read-only: it reads the log and
never changes how it is written, restarts nothing, starts nothing and sends nothing. It is the same shape as the
[delivery audit](delivery-audit.md): a pure function over rows, T0 counts kept in the dict, one digit-free
label, a read-only tool and CLI, and a doctor row.

## The log and the fields relied on

The sync appends one row per run:

    {"at": "...Z", "job": "sync", "ok": true|false, ...}                   older rows
    {"at": "...Z", "job": "sync", "ok": true|false, "inputs": "stale a,b,c", ...}   newer rows

- `"at"`: an ISO-8601 UTC time; the run's local day is read in this machine's zone (the tool and the CLI), or
  the zone the caller passes. A row whose `"at"` cannot be read is skipped and counted.
- `"inputs"`: the string `"stale a,b,c"`: the input names (camelCase, as in `inputs.json`) that were stale on
  that run, comma separated; `"stale"` with no name means none was. A row with no `inputs` key, or any other
  value, is unknown for that run: never fresh and never stale.

Nothing else in the row is used. In particular `"ok"` is not read here: a failed run that still names its
stale inputs counts like any other.

## Rules

- Window: the last `uptime_days` local days up to today (config, a whole number, default 28).
- Per input and day: fresh when at least one run that day has `"inputs"` and does not list the input; stale
  when every such run lists it; unknown when the day has no run, or only rows with no `inputs` key. unknown is
  never counted as fresh or stale, so a gap in the log is unknown, not zero.
- Inputs judged: the names in `inputs.json` (in its order) plus every name a run in the window lists, minus
  config `outage_ignore` (the same names the outage line leaves out).
- Every-input-fresh day: a known day on which no judged input is stale.
- Uptime goal (config `uptime_target`, a share above zero and at most one, default 0.95): met when the
  every-input-fresh days reach that share of the whole window, rounded up (27 of 28 days by default). Not met
  when even every unknown day being fresh would not reach it. Otherwise unknown: an unknown day never counts
  for the goal.
- Fewer than seven known days in the window: the whole label is `unknown`.
- Only local dates: no clock time and no time-of-day rule.

The numbers are T0 and stay in the audit dict. The T1 label is words with no digit, joined with "; ": the inputs
grouped by phrase, best first, then the goal:

- per input: "fresh every day", "fresh every known day", "fresh most days" (fresh on more than half of the
  known days), "fresh about half the days", "stale most days", "stale every known day", and "stale all week" /
  "stale all month" / "stale every day" when stale on every day of a seven-day / four-week / other window;
  input names in words, camelCase split as the outage line does ("phone apps", "desktop AW");
- "no input was reported stale" when no input is named at all;
- goal: "uptime goal met", "uptime goal not met", "uptime goal unknown: too many days without input words".

## Loop gaps: when the loop itself was down

The day-by-day rules above judge whether the inputs were fresh; they do not say whether the sync ran at all.
When the host goes down (out of memory, a reboot) the runs simply stop. The audit also reads the run times
themselves, from the rows' own `"at"`:

- The usual spacing is the median spacing between consecutive runs in the window (rows with or without
  `inputs` alike; a torn line is skipped and counted as above).
- A gap is two consecutive runs further apart than the limit: config `loop_gap_limit_s` (seconds, above zero),
  else three times that median spacing. A gap is one "loop down" stretch. No clock time: only the runs'
  spacing is read, never a time of day.
- An open gap: the newest run up to now is older than the limit (runs stamped after now are left out).
- In words, only when the label is known (too few rows keep the `unknown` words unchanged):
  - an open gap comes first: "the loop has not run for under an hour" / "for hours" / "for over a day";
  - closed gaps that ended in the last seven local days add one clause before the goal: "the loop stopped once
    this week for hours", or "the loop stopped a few times this week, the longest for over a day" ("for under
    an hour", "for hours", "for over a day" is the longest one);
  - no gap: no clause. No count, no time stamp and no host name is ever said.
- The gap times and lengths are T0 and stay in the audit dict (`loop`). The words never set a status: the
  doctor row still follows the uptime goal alone, and the scorecard never sets a status either.

## Where it shows

- Tool `limitless_uptime`, read-only: `{value: {label}, modality: "measured", age_h, evidence_tier}` with the T1
  label beside it, aged by the newest run in the window. The counts (fresh, stale and unknown days per input,
  per-day rows, every-input-fresh days, the target, skipped lines) appear only with the raw opt-in
  (`LIMITLESS_RAW_IN_PROMPT=1`). No `runs.jsonl`, no run in the window, or fewer than a week of runs that name
  their stale inputs is value `null` with a reason and the label `unknown`: unknown, not zero. Reasons never
  echo a path.
- `bin/limitless-uptime-audit`: prints the label, or `unknown: <why>`; `--json` prints the counts (for the
  operator's terminal, not a model). Read-only, exit 0.
- `limitless-doctor`: an `uptime` row right after `last sync run`, kind `source` (so `--strict` never counts
  it): live when the goal was met, stale when it was not, missing when unknown; the reason is the label's words
  or why it is unknown, never a count. The doctor also lists `tool limitless_uptime` like every tool.
- The north-star scorecard (`limitless/scorecard.py`) never reads the evidence column of the hand-kept table
  (it may hold private detail); it cites this audit itself instead. `scorecard.measured(state_dir, cfg, now,
  tz)` reads row one through `tools.uptime_audit` (the same read as `limitless_uptime` and the doctor) and
  gives `{n, criterion_words, label, goal}`: the label above, or `unknown: <why>` (no `runs.jsonl`, no run in
  the window, too few known days), never an error and never met. The weekly block
  (`bin/limitless-scorecard`, when the state dir exists) ends with `Measured: loop uptime: <label>`, and when
  the hand status of row one is green but the goal is not met, one more line:
  `Row <name> says green but the measurement says not met.` These lines take the place of the lowest-priority summary lines, so the block
  keeps its five lines. `limitless_scorecard` carries the same in its `measured` field (the label as T1, the
  goal, the note; the counts only with the raw opt-in). The audit never marks the row green and never changes
  a status: green still needs the goal met over the whole window, judged by the person. Rows three, four and
  seven are measured the same way ([scorecard-measured.md](scorecard-measured.md)).

## Known gap

The sync is not part of this repo. If it leaves `inputs` out of a newer row when nothing is stale, that row
reads as unknown here, never fresh (the same as an older row), so a day with no stale input can show as
unknown. The fix belongs in the sync: write `"inputs": "stale"` (no names) when every input is fresh. Until
then the goal reads unknown or not met rather than met: it errs low, never high.

## Example

`python3 -I scripts/uptime_audit_example.py`: four weeks of synthetic rows (six older rows with no `inputs`
key, a wearable stale for a week, a desktop source stale on and off, a day stale early and fresh later, and two
days with no run at all), then hourly runs with a loop that stopped, at a fixed clock in UTC. Real output:

```text
# limitless_uptime, no raw opt-in (default window: four weeks, target nineteen days in twenty)
{"value": {"label": "phone apps and phone unlocks fresh every known day; wearable fresh most days; desktop AW stale most days; uptime goal not met"}, "modality": "measured", "age_h": 11.0, "evidence_tier": "direct"}
{"label": "phone apps and phone unlocks fresh every known day; wearable fresh most days; desktop AW stale most days; uptime goal not met", "tier": "T1", "modality": "measured"}

# the same with the raw opt-in: T0 counts per input, then per day (null = unknown day)
phoneApps {"fresh": 20, "stale": 0, "unknown": 8}
phoneUnlocks {"fresh": 20, "stale": 0, "unknown": 8}
wearable {"fresh": 13, "stale": 7, "unknown": 8}
desktopAW {"fresh": 5, "stale": 15, "unknown": 8}
{"window_days": 28, "known_days": 20, "all_fresh_days": 5, "all_fresh_share": 0.17857142857142858, "target": 0.95, "goal": "not met", "skipped": 1}
{"day": "2033-05-07", "runs": 1, "known_runs": 1, "stale": ["desktopAW"], "all_fresh": false}
{"day": "2033-05-08", "runs": 1, "known_runs": 1, "stale": ["desktopAW"], "all_fresh": false}
{"day": "2033-05-09", "runs": 2, "known_runs": 2, "stale": [], "all_fresh": true}
{"day": "2033-05-10", "runs": 0, "known_runs": 0, "stale": null, "all_fresh": null}
{"day": "2033-05-11", "runs": 0, "known_runs": 0, "stale": null, "all_fresh": null}
{"day": "2033-05-12", "runs": 1, "known_runs": 1, "stale": [], "all_fresh": true}
{"day": "2033-05-13", "runs": 1, "known_runs": 1, "stale": ["desktopAW"], "all_fresh": false}
{"day": "2033-05-14", "runs": 1, "known_runs": 1, "stale": [], "all_fresh": true}
{"day": "2033-05-15", "runs": 1, "known_runs": 1, "stale": ["desktopAW"], "all_fresh": false}
{"day": "2033-05-16", "runs": 1, "known_runs": 1, "stale": [], "all_fresh": true}
{"day": "2033-05-17", "runs": 1, "known_runs": 1, "stale": ["desktopAW"], "all_fresh": false}
{"day": "2033-05-18", "runs": 1, "known_runs": 1, "stale": [], "all_fresh": true}

# config outage_ignore: ["desktopAW"] (the same names the outage line leaves out)
phone apps and phone unlocks fresh every known day; wearable fresh most days; uptime goal not met

# config uptime_days: 7, outage_ignore: ["desktopAW"]
phone apps, phone unlocks and wearable fresh every day; uptime goal met

# only older rows (no inputs key): unknown, never fresh
{"value": null, "modality": "measured", "age_h": null, "evidence_tier": "none", "reason": "fewer than a week of sync runs name their stale inputs"}

# a loop that stopped: hourly runs, none for eight hours three days ago and none in the last five hours
the loop has not run for hours; phone apps, phone unlocks, wearable and desktop AW fresh every day; the loop stopped once this week for hours; uptime goal met
# the same with config loop_gap_limit_s: eight hours (neither stretch is over it)
phone apps, phone unlocks, wearable and desktop AW fresh every day; uptime goal met

# runs.jsonl is unchanged: 28 lines
```
