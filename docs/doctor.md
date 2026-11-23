# limitless-doctor: which inputs are live, and which tools would answer unknown

`bin/limitless-doctor` is the operator's one read-only check of the configured install before a briefing or a
"done": instead of hand-written probes per feature, one command says, in words, which inputs are live and which
plugin tools would answer unknown, and why.

```
bin/limitless-doctor            # one line per row: name: status: reason
bin/limitless-doctor --json     # the full rows: [{"name", "kind", "status", "reason"}, ...]
bin/limitless-doctor --strict   # the same report; exit 1 when the state dir, an input or the last sync run is not live
```

It reads the same config the plugin reads (`LIMITLESS_CONFIG`, else `~/.config/limitless/config.json`; the state
dir is `LIMITLESS_STATE`, else `"state"` there).

## Rows

| Row | kind | live | stale | missing | off |
|---|---|---|---|---|---|
| `state dir` | state | exists and is readable | | does not exist, or is not readable | |
| `input <name>`, one per name in `inputs.json` | input | recording: within `STALE_H` (the `limitless_status` rule: the snapshot's age plus the input's age) | over the threshold, or reported `down` | no age for it; no `inputs.json` at all is one `inputs` row | |
| `last sync run` | run | the last valid row of `runs.jsonl` is at most `STALE_H` old and did not fail | older, or it failed | no timestamped row | |
| `tool <name>`, one per tool in `plugin.yaml`, in its order | tool | the tool answers with a value (its evidence tier in words) | it answers, but its evidence tier is stale | `value` is null, or the value is `unknown`: the envelope's own reason | the reason says its input is not set in config, or the feature is off by config (focus guard, breathing link, card dir) |

The thresholds are the plugin's own (`envelope.STALE_H`, the one `limitless_status` and the labeler use); the
doctor adds none. A tool row comes from calling that tool's plugin function with `{}` the way its handler does
(`tools.labeled`, then `tier_audit.audit_result`). A tool that needs arguments (`limitless_capture`) says so in
front of its reason. A tool that raises is `missing` with the exception's type only, never its message.

## What it never does

- It never writes: not a state file, not a capture, not a card file (`limitless_card_view` is called with
  `write=False`: rendered only) and not an audit line (the tool calls run inside `tier_audit.held`, which pauses
  the audit log; a digit is still blocked). A test runs the whole report on a synthetic state dir and checks
  every file's mtime and bytes.
- It never sends, never pushes and never starts a job.
- A tool's value is never printed: only the status and a reason in words. Every number in a reason becomes
  "a number", so no line holds a digit, even under the person's raw opt-in (`LIMITLESS_RAW_IN_PROMPT=1`). A test
  plants obvious raw numbers in a synthetic state and checks that none of them appear, in text or `--json`.
- Exit 0 always: it is a report, not a gate. Only `--strict` exits 1, and only for a state dir, input or last
  sync run row that is not live; tool rows never fail it.

## Example (synthetic)

The real output of `python3 -I scripts/doctor_example.py`: the synthetic fixture state
(`tests/fixtures/state`: six inputs, one down, a sync run log) plus a made-up idea ledger, at the fixture clock.

```text
$ limitless-doctor
state dir: live: the state dir exists and is readable
input activitywatch: live: recording: updated within the last day
input anki: stale: not recording: no update for over a day
input bike: stale: not recording: the sync reports it down
input phone: live: recording: updated within the last day
input scale: stale: not recording: no update for over a day
input wearable: live: recording: updated within the last day
last sync run: live: the last sync run was about an hour ago and finished ok
tool limitless_status: live: answers from direct evidence
tool limitless_state: live: answers from a proxy
tool limitless_window: live: answers from a proxy
tool limitless_habit: live: answers from direct evidence
tool limitless_habit_next: live: answers, with nothing measured behind it yet
tool limitless_skill_tree: live: answers, with nothing measured behind it yet
tool limitless_scorecard: off: no scorecard path: set LIMITLESS_SCORECARD or "scorecard" in config.json
tool limitless_capture: missing: needs its arguments: empty capture: nothing recorded
tool limitless_catchup: off: no owner session DBs or beacons: set LIMITLESS_OWNER_DBS or LIMITLESS_OWNER_BEACONS (config "owner_dbs" or "owner_beacons")
tool limitless_body: off: no body file: set "body_file" in config.json
tool limitless_overnight: off: no work queue: set "work_queue_dir" in config.json
tool limitless_rides: off: no rides file: set "rides_file" in config.json
tool limitless_anki: off: no Anki collection set
tool limitless_sleep: missing: no sleep data: no wearable file (set "sleep_file" in config.json) and no phone screen events
tool limitless_loop: missing: no week decided yet: no loop row
tool limitless_experiment: live: answers, with nothing measured behind it yet
tool limitless_naps: live: answers from a proxy
tool limitless_presleep_hr: off: no pre-sleep heart-rate file: set "presleep_hr_file" in config.json
tool limitless_breathing: off: no breathing link set (config wind_down_breathing_link)
tool limitless_quiet: stale: answers, but its evidence is stale or of unknown age
tool limitless_blocks: missing: focus blocks unknown: no readable ActivityWatch DB (aw_db)
tool limitless_flow_metrics: missing: flow metrics unknown: no readable ActivityWatch DB (aw_db)
tool limitless_flow_ledger: off: flow ledger unknown: no work apps set (flow_work_apps)
tool limitless_ideas: stale: answers, but its evidence is stale or of unknown age
tool limitless_phase: live: answers from a proxy
tool limitless_explain_back: stale: answers, but its evidence is stale or of unknown age
tool limitless_propose: stale: answers, but its evidence is stale or of unknown age
tool limitless_schedule: live: answers from direct evidence
tool limitless_card_view: off: no card dir set (config card_dir): the card is rendered only
tool limitless_focus_safe: off: the focus guard is off (config focus_safe)
$ limitless-doctor --strict > /dev/null; echo $?
1
```
