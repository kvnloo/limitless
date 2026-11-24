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
| `uptime`, right after the last sync run | source | every input was fresh on at least config `uptime_target` of the last `uptime_days` local days of `runs.jsonl` (the uptime goal met); the reason is `limitless_uptime`'s words, never a count | the goal was not met, even counting every unknown day as fresh | no `runs.jsonl`, no run in the window, fewer than a week of runs that name their stale inputs, or too many unknown days to tell ([uptime-audit.md](uptime-audit.md)) | |
| `delivery`, right after the uptime row | source | north-star row two met as the scorecard measures it (`delivery_audit.goal` over config `push_log`, complaints from config `hermes_db` and `quiet.json`); the reason is `limitless_delivery`'s words, never a count or a reply | the goal was not met (over the push limit, a missed brief, a push with no reply line, a quiet or stop request, or "the last pushes failed to send") | the goal is unknown: an unreadable log, no row this week, unknown wake days, or complaints unknown (no Hermes DB set, or it cannot be read) ([delivery-audit.md](delivery-audit.md)) | no `push_log` set |
| `push sender`, right after the delivery row | source | `set: the sender profile exists`: the Hermes profile `bin/kevin-push` sends through (`KEVIN_PUSH_PROFILE`, else config `push_profile`, else the default) is `default`, or its dir exists under the Hermes home's `profiles/` (the home as `hermes -p` resolves it: `HERMES_HOME`, or its grandparent when it is a `<root>/profiles/<name>` profile home, else `~/.hermes`); only the dir is checked, hermes is never run and nothing is sent | | `broken: the sender profile does not exist` (every send would fail and only be logged), or `unknown:` no Hermes home is set, it does not exist, or it cannot be read; never the profile name, the target or a path | |
| `Sleep mode`, right after the push sender row | source | the last row of `sleepmode.jsonl` (`LIMITLESS_SLEEPMODE`, else the state dir; the file kevin-push's Sleep hold reads) is `off`, or `on since <age in words>`; an on row adds "the Sleep mode poll is not fresh, so pushes are not held" while `sleepmode-poll.json` is not ok or older than kevin-push's limit (it fails open) | `left on, ignored since the owner was seen up`: the last row is the poller's inferred off row with `left_on`; or `stale: on far longer than a night; pushes are being held`: on longer than `sleepmode.NIGHT_H` with no such row ([below](#sleep-mode-row)) | `unknown:` no file, it cannot be read, no row with a time and an on or off, or the last row is in the future | |
| `local labeler`, right after the Sleep mode row | labeler | `set:` `LIMITLESS_T1_CMD` or config `t1_model_cmd` names a command whose program exists and, for the bundled runner `bin/limitless-t1-local`, its model binary and model file (`LIMITLESS_T1_BIN` / `LIMITLESS_T1_MODEL`, else config `t1_bin` / `t1_model`) exist too; only files are checked, the model is never run. The reason says whether a passing local model check (`bin/limitless-t1-check`) is on file: `set: checked, agrees on most checks` (config `t1_check_file`, at least `t1_min_agreement`), or `set: not checked yet` (no check file set, so none is required) | | `broken:` the command cannot be read, its program does not exist, or the runner's binary or model file is not set or does not exist; the rule labels are used | no local model command set (the default): the rule labels are used; or set with config `t1_check_file` but no passing check on file (`set: not checked yet, ...` or `set: checked, agrees on few checks, below the minimum, ...`): the rule labels are used until one is ([privacy-tiers.md](privacy-tiers.md#local-model-labeler), [the check](privacy-tiers.md#local-model-check)) |
| `tool <name>`, one per tool in `plugin.yaml`, in its order | tool | the tool answers with a value (its evidence tier in words) | it answers, but its evidence tier is stale | `value` is null, or the value is `unknown`: the envelope's own reason | the reason says its input is not set in config, or the feature is off by config (focus guard, breathing link, card dir) |
| `NOOP MCP`, right after the tools | mcp | | | config `noop_mcp` is set but malformed; `refused: t0_tools does not cover its tools`; or set and covered, to be added to the host's `mcp_servers` by hand (the host has no plugin API for it; the doctor cannot see `mcp_servers`) | `noop_mcp` is unset (the default) ([noop-mcp.md](noop-mcp.md)) |
| `desktop AW`, after the NOOP MCP row | source | config `desktop_aw_url` (or `desktop_aw_export`) is set and shows active app time within `STALE_H`, its age in words | it answers with no active app time in that time | `unreachable:` it does not answer, or what it sends cannot be used (no window bucket, no afk bucket, not ActivityWatch data); the plain reason | neither is set (the default); nothing is called ([desktop-aw.md](desktop-aw.md)) |
| `feed reflex`, after the desktop AW row | source | config `feed_apps` and `aw_db` are set and the last week has enough unlocks to say (`feed_reflex_min_unlocks`); never the words it would say | | `unknown:` no readable DB, no unlock, or too few unlocks; the plain reason | `feed_apps` is not set (the default) ([feed-reflex.md](feed-reflex.md)) |
| `apps lists`, after the feed reflex row | source | the work-app or feed-app list is set; the reason says, per list, "set from the environment", "set from config" or "set from a reply" (`apps.json`), or "not set"; never an app name | | | neither list is set (the default) ([apps-ingest.md](apps-ingest.md)) |
| `apps ask`, after the apps lists row | source | config `apps_ask` is on (the default); the reason starts with "waiting" (the next wake brief proposes the lists), "told recently" (asked in a delivered brief less than a week ago, `apps-ask.json`) or "not needed" (a list is set); never an app name | | | `apps_ask` is `off` ([apps-ask.md](apps-ask.md)) |
| `job apps ingest`, after the apps ask row | job | config `apps_ingest` is `dry_run` or `write`, a Hermes DB is set (config `hermes_db`) and the job ran after the newest sync run; the reason says the mode, when it ran and what it did ("wrote the app lists", "would write the app lists", "no new apps reply"; `apps-ingest.json`), never an app name | | on, but no Hermes DB is set, no sync run yet, or a sync it has not run after yet | `apps_ingest` is `off` (the default) ([apps-ingest.md](apps-ingest.md#as-an-event-job)) |
| `sleep coverage`, after the context packet's row and just before the two wearable export rows | source | the wearable recorded sleep (config `sleep_file`, demo rows dropped) on at least config `sleep_coverage_target` of the last `sleep_coverage_days` local nights (the wearable goal met); the reason is `limitless_sleep_coverage`'s words, never a count | the goal was not met, even counting every unknown night as wearable | the sleep file is missing or unreadable, no night has any data, fewer than a week of nights are known, or too many nights have no data to tell ([sleep-coverage.md](sleep-coverage.md)) | no `sleep_file` set |
| `ranked ledger`, after the apps ingest row | source | `$LIMITLESS_RANKED_LEDGER` or config `ranked_ledger` names a ledger with valid rows; the reason is "rows read: " and scorecard row ten's own words ("some of the ranked items verified or dropped by the owner"), plus "some lines could not be read and were skipped" when a line was torn or another shape; never an id, evidence text or a count | | `broken:` the ledger is missing or cannot be read, or has no valid rows ([ranked-ledger.md](ranked-ledger.md)) | no ranked ledger set (the default) |
| `job ranked ingest`, after the ranked ledger row | job | config `ranked_ingest` is `dry_run` or `write` and the job ran after the newest sync run; the reason says the mode, when it ran and its result in words ("appended owner drop rows", "would append owner drop rows", "no owner drop to append", "no new owner message"; `ranked-ingest.json`), never an id | on, but no sync run yet, or a sync it has not run after yet | `broken:` on, but no ranked ledger or no Hermes DB is set, or the ledger is missing or cannot be read | `ranked_ingest` is `off` (the default) ([ranked-ledger.md](ranked-ledger.md#as-an-event-job)) |
| `job voice MIQ`, after the ranked ingest row | job | config `voice_miq` is `dry_run` or `write` and config `voice_miq_sessions` names a dir that exists; the reason says the mode and when the last spoken MIQ answer was captured (`voice-miq.json`) | | on, but `voice_miq_sessions` is unset or the dir does not exist | `voice_miq` is `off` (the default) ([voice-miq.md](voice-miq.md)) |
| `export context packet`, after the voice MIQ row | export | config `context_packet_path` is set and the packet there was written (`limitless-context-packet --write`) within `STALE_H` by its own `generated_at` | set but not written yet; older than `STALE_H`; or the file is not a `limitless.context/1` packet | | `context_packet_path` is unset (the default) ([context-packet.md](context-packet.md)) |
| `export Open Wearables`, before the NOOP job | export | config `open_wearables_export` is `dry_run` or `write` and the last `limitless-ow-export` run read the server within `STALE_H` (`open-wearables.json`) | on but it has not run yet; its last good run is older; or `failing:` its last run could not read the server or write the sleep file (the plain reason) | | `open_wearables_export` is `off` (the default) ([open-wearables.md](open-wearables.md)) |
| `job NOOP export`, last | job | config `noop_export` is `dry_run` or `write` and the export ran after the newest sync that copied the NOOP database, and exported (`noop-export.json`) | a sync copied the NOOP database and it has not run after it yet; no sync has copied it yet; or its last run found nothing to export (the plain reason) or could not write a file | | `noop_export` is `off` (the default) ([noop-export.md](noop-export.md)) |

The thresholds are the plugin's own (`envelope.STALE_H`, the one `limitless_status` and the labeler use); the
doctor adds none. A tool row comes from calling that tool's plugin function with `{}` the way its handler does
(`tools.labeled`, then `tier_audit.audit_result`). A tool that needs arguments (`limitless_capture`) says so in
front of its reason. A tool that raises is `missing` with the exception's type only, never its message.

## Sleep mode row

kevin-push holds every non-critical push while the last row of `sleepmode.jsonl` says on and the poll
heartbeat next to it (`sleepmode-poll.json`) is ok and fresh; a stale poll fails open and nothing is held. The
poller that writes the file closes a phone Sleep rule left on far longer than a night once the owner is seen up,
with an inferred off row `{"on": false, "inferred": "Sleep left on, owner up", "left_on": "<rule id>"}`, and
ignores that rule after; newer on rows also carry `"rule"`. The `Sleep mode` row reads the same file
(`LIMITLESS_SLEEPMODE`, else the state dir) and says which case holds, in words only (no clock time, no digit,
never the rule id or a path):

- `off`: the last row is a plain off row (old rows without `rule` or `left_on` read the same).
- `on since <age in words>`: counted from the first on row of the current activation; plus "the Sleep mode poll
  is not fresh, so pushes are not held" when kevin-push would fail open.
- `left on, ignored since the owner was seen up` (stale): the last row is the poller's inferred off row with
  `left_on`. Pushes go out; the phone rule is still on and no longer means sleep.
- `stale: on far longer than a night; pushes are being held`: on for longer than `sleepmode.NIGHT_H` (sixteen
  hours, the longest one night keeps Sleep mode on) with no `left_on` row yet. With a poll that is not fresh it
  says pushes are not held instead.
- `unknown: <reason>` (missing): no file, it cannot be read, no row with a time and an on or off, or the last
  row is in the future.

The delivery audit uses the same `left_on` rows to tell a brief held by a night from one held while Sleep mode
was left on ([delivery-audit.md](delivery-audit.md#why-a-wake-brief-was-missed)).

The real output of `python3 -I scripts/sleep_mode_doctor_example.py` (made-up files, a fixed clock, UTC):

```text
# a night that ended (old rows: no rule, no left_on)
Sleep mode: live: off
# on since a nap began, poll fresh
Sleep mode: live: on since about three hours ago
# the same, but the poll stopped
Sleep mode: live: on since about three hours ago; the Sleep mode poll is not fresh, so pushes are not held
# a rule left on, not closed yet
Sleep mode: stale: stale: on far longer than a night; pushes are being held
# the poller closed it once the owner was seen up
Sleep mode: stale: left on, ignored since the owner was seen up
# no sleepmode.jsonl at all
Sleep mode: missing: unknown: no Sleep mode file in the state dir
```

## What it never does

- It never writes: not a state file, not a capture, not a card file (`limitless_card_view` is called with
  `write=False`: rendered only) and not an audit line (the tool calls run inside `tier_audit.held`, which pauses
  the audit log; a digit is still blocked). A test runs the whole report on a synthetic state dir and checks
  every file's mtime and bytes.
- It never sends, never pushes and never starts a job. The `push sender` row never runs hermes: it only checks
  that the profile dir exists (a test fails if any process is started).
- It never runs the local T1 model: the `local labeler` row only checks that files exist and reads the saved
  check words, and the tool rows label with the rules only (`labeler.rules_only`), even when `t1_model_cmd` is
  set. The local model check runs only when `bin/limitless-t1-check` is called.
- A tool's value is never printed: only the status and a reason in words. Every number in a reason becomes
  "a number", so no line holds a digit, even under the person's raw opt-in (`LIMITLESS_RAW_IN_PROMPT=1`). A test
  plants obvious raw numbers in a synthetic state and checks that none of them appear, in text or `--json`.
- Exit 0 always: it is a report, not a gate. Only `--strict` exits 1, and only for a state dir, input or last
  sync run row that is not live; tool, job, export and MCP rows never fail it.

## Example (synthetic)

The real output of `python3 -I scripts/doctor_example.py`: the synthetic fixture state
(`tests/fixtures/state`: six inputs, one down, a sync run log) plus a made-up idea ledger and a made-up Hermes
home that holds the default sender profile's dir, at the fixture clock.

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
uptime: missing: fewer than a week of sync runs name their stale inputs
delivery: off: no push log set (config push_log)
push sender: live: set: the sender profile exists
Sleep mode: live: off
local labeler: off: no local model command set, so the rule labels are used
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
tool limitless_sleep_debt: missing: no sleep data: no wearable file (set "sleep_file" in config.json) and no phone screen events
tool limitless_sleep_coverage: off: no wearable sleep file: set "sleep_file" in config.json
tool limitless_loop: missing: no week decided yet: no loop row
tool limitless_experiment: live: answers, with nothing measured behind it yet
tool limitless_naps: live: answers from a proxy
tool limitless_outages: live: answers from direct evidence
tool limitless_presleep_hr: off: no pre-sleep heart-rate file: set "presleep_hr_file" in config.json
tool limitless_breathing: off: no breathing link set (config wind_down_breathing_link)
tool limitless_quiet: stale: answers, but its evidence is stale or of unknown age
tool limitless_blocks: missing: focus blocks unknown: no readable ActivityWatch DB (aw_db)
tool limitless_flow_metrics: missing: flow metrics unknown: no readable ActivityWatch DB (aw_db)
tool limitless_flow_ledger: off: flow ledger unknown: no work apps set (flow_work_apps)
tool limitless_feed_reflex: off: feed reflex unknown: no feed apps set (config feed_apps)
tool limitless_app_candidates: off: app candidates unknown: no ActivityWatch source set (aw_db, desktop_aw_url or desktop_aw_export)
tool limitless_ideas: stale: answers, but its evidence is stale or of unknown age
tool limitless_delivery: off: no push log set (config push_log)
tool limitless_uptime: missing: fewer than a week of sync runs name their stale inputs
tool limitless_phase: live: answers from a proxy
tool limitless_explain_back: stale: answers, but its evidence is stale or of unknown age
tool limitless_propose: stale: answers, but its evidence is stale or of unknown age
tool limitless_palace: off: no memory palace link set (config palace_link)
tool limitless_schedule: live: answers from direct evidence
tool limitless_card_view: off: no card dir set (config card_dir): the card is rendered only
tool limitless_focus_safe: off: the focus guard is off (config focus_safe)
tool limitless_result_tier: off: no health tools listed (config t0_tools)
NOOP MCP: off: no noop_mcp set
desktop AW: off: desktop ActivityWatch is not set (desktop_aw_url or desktop_aw_export)
feed reflex: off: no feed apps set (config feed_apps)
apps lists: off: no work apps or feed apps set (config flow_work_apps, feed_apps, or a reply)
apps ask: live: waiting: the next wake brief proposes the app lists once app time names a work or feed app
job apps ingest: off: the apps ingest job is off (config apps_ingest)
ranked ledger: off: no ranked ledger set (LIMITLESS_RANKED_LEDGER or config "ranked_ledger")
job ranked ingest: off: the ranked ingest job is off (config ranked_ingest)
job voice MIQ: off: the voice MIQ is off (config voice_miq)
export context packet: off: the context packet is not written (config context_packet_path)
sleep coverage: off: no wearable sleep file: set "sleep_file" in config.json
export Open Wearables: off: the Open Wearables export is off (config open_wearables_export)
job NOOP export: off: the NOOP export job is off (config noop_export)
$ limitless-doctor --strict > /dev/null; echo $?
1
```
