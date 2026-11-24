# Scorecard: what code measured

The north-star scorecard (`limitless/scorecard.py`) is a hand-kept Markdown table: the person sets each row's
status (red, amber, green). Code never reads the evidence column and never changes a status. Beside the hand
status it says, in words, what code measured for the rows it can measure from data the plugin already writes.

    scorecard.measured_audits(state_dir, cfg, now, tz)  -> [(row, audit)] for rows 1, 2, 3, 4, 5, 6, 7, 8 and 10
    scorecard.measured(state_dir, cfg, now, tz)         -> [{n, criterion_words, label, goal}]
    scorecard.measured_lines(rows, measured)            -> the weekly block's measured lines (at most four)

`label` is digit-free T1 words, or `unknown: <why>`; `goal` is met, not met or unknown, and unknown is never
met. A missing, torn or unreadable file is unknown, never an error. Read-only: nothing is written or sent, no
second store is kept, and code never marks a row green.

## The nine measured rows

| Row | Words | Read from |
|---|---|---|
| 1 | loop uptime | the uptime audit of the sync's `runs.jsonl` ([uptime-audit.md](uptime-audit.md)) |
| 2 | delivery | the delivery audit of kevin-push's log, config `push_log` ([delivery-audit.md](delivery-audit.md)) |
| 3 | habit loop | the stop rule's loop rows in `predictions.jsonl` and the habit files ([stop-rule.md](stop-rule.md)) |
| 4 | evidence loop | the locks and receipts in `predictions.jsonl` ([experiment.md](experiment.md)) |
| 5 | foundation | the sleep coverage audit of config `sleep_file` ([sleep-coverage.md](sleep-coverage.md)) |
| 6 | flow | flow_week over the last finished week ([flow-week.md](flow-week.md)) |
| 7 | privacy | `tier_audit.check` over the tier audit log ([privacy-tiers.md](privacy-tiers.md)) |
| 8 | integrated | the local integrations: Glide, the call brief, the asks queue, the voice MIQ |
| 10 | top items | an optional private ranked ledger, config `ranked_ledger` |

Row 9 is not measured: it stays on the hand status alone.

### Row 3, "Habit loop: 4 weekly cycles"

A cycle is one habit week that has a confirmed start (`habit.json` or a kept `habit-<week_of>.json` naming a
habit and a `week_of`, which `habit_start` writes only after the person said yes, or the week's loop row) and a
Keep or Drop decision row (`stop_rule.loop_rows`, the `kind: "loop"` rows in `predictions.jsonl`).

- met: the last four habit weeks each closed with a Keep or Drop decision ("the last four habit weeks each
  closed with a Keep or Drop decision");
- not met: a finished week (its seven days past) among those last four has no decision ("a finished habit week
  has no Keep or Drop decision"), or fewer than four weeks have closed so far ("fewer than four habit weeks
  closed with a decision so far");
- unknown: no habit week was ever started ("unknown: no habit week started").

The running week, still undecided inside its seven days, is open and never counts against the goal. Skipped and
unanswered days never count against a cycle: the day answers are not read at all, only the start and the
decision. An older undecided week before the last four no longer counts.

### Row 4, "Evidence loop: >=2 locked N-of-1 experiments with outcome receipts"

Count the locked predictions (`kind: "prediction"`, one per week, `prediction.locked`) that have a judged
receipt (`prediction.receipt_for`: the receipt written for that lock, with the verdict supports, contradicts or
inconclusive, not pending).

- met: two or more locked experiments have a judged receipt;
- not met: at least one lock exists but fewer than two are judged;
- unknown: none was ever locked ("unknown: no experiment locked"); unknown is never met.

### Row 5, "Foundation measured honestly"

The row reuses the sleep coverage audit as it is (`tools.sleep_coverage_audit`, the same read as
`limitless_sleep_coverage` and the doctor's sleep coverage row): its own goal (wearable sleep on at least
`sleep_coverage_target` of the last `sleep_coverage_days` nights, default four in five over four weeks) and its own
unknown rules. The rule is not re-implemented here.

- met / not met: sleep_coverage's goal, with its own label ("wearable sleep on every night; wearable goal met");
  the phone estimate never counts as wearable and demo rows never count;
- unknown: no sleep file set, a missing or unreadable one, no night with any data, or fewer than a week of known
  nights (`unknown: <sleep_coverage's reason>`).

### Row 6, "Flow reported weekly (deep-work minutes, feed leak)"

`flow_week.week` over the last finished week: the seven local days before today (today is still running and
never counts). The inputs are the ones `flow_week.for_week` reads: the ActivityWatch DB (`$LIMITLESS_AW_DB`, else
config `aw_db`), the desktop's ActivityWatch (config `desktop_aw_url` or `desktop_aw_export`), the work-app list
(`$LIMITLESS_FLOW_WORK_APPS`, else config `flow_work_apps`, else `apps.json` set from a reply), the feed apps and
Glide's focus block (`$LIMITLESS_GLIDE_ATTENTION`, else config `glide_attention`).

- met: the week has a known deep-work amount and a known feed leak ("deep work and feed leak measured for the
  last finished week");
- not met: work apps are set and the week has data, but either part is unknown, with flow_week's own reason
  ("deep work measured but feed leak unknown for the last finished week: no focus blocks");
- unknown: no work-app list is set ("unknown: no work apps set") or there is no activity data for the week
  ("unknown: no activity data in the last finished week").

The trend is never judged: the row asks only whether the week was reported, so no better or worse word and no
score; the numbers sit in the tool's `counts` under the raw opt-in.

### Row 7, "Privacy: no raw health data above T1, 0 leaks"

`tier_audit.check` over the configured audit log (`$LIMITLESS_AUDIT`, else config `audit_path`) for the last
seven days:

- met: the log has rows in the window and nothing digit-bearing (a card or a tool result) went out without the
  opt-in; blocked rows are fine: they were stopped, never sent;
- not met: one went out without the opt-in (a T0 row that is not blocked and has no opt-in);
- unknown: no audit log is set ("unknown: no audit log set") or it has no rows in the window ("unknown: no
  audit rows this week").

### Row 8, "Integrated (Glide, z0live voice brief, ayo windows, z0 registry)"

One sub-check per local integration the plugin can see, each live, stale, missing or off (not set up):

- Glide: the attention file (`$LIMITLESS_GLIDE_ATTENTION`, else config `glide_attention`) reads as a JSON object;
- call brief: the file at config `call_brief_file` (a relative path is in the state dir) was written within
  `call_brief.STALE_S` (three hours, z0live's own freshness rule; older, or a future time, is stale);
- asks queue: the queue (`$LIMITLESS_ASKS`, else config `asks_path`) is set and can be read (an empty queue is
  fine);
- voice MIQ: config `voice_miq` is on and its call sessions dir (config `voice_miq_sessions`) exists.

The z0 registry cannot be checked locally: the audit dict says "z0 registry: not measured here" and it is never
counted live.

- met: all four local sub-checks are live ("Glide, call brief, asks queue and voice MIQ all live");
- not met: at least one is set up but not all four are live; the label names, in words, each one that is not live
  ("not live: call brief stale, voice MIQ not set up");
- unknown: none is set up ("unknown: no local integration set up").

### Row 10, "Top-25 ranked items done-verified or dropped"

An optional private ledger (`$LIMITLESS_RANKED_LEDGER`, else config `ranked_ledger`; a relative path is in the
state dir; the repo ships none), one JSON row per line: `{"id": str, "status": "open" | "built" | "verified" |
"dropped", "by": str, "evidence": str}`. The newest row per id wins (a later line replaces an earlier one).

- "verified" counts only with a non-empty evidence string; "dropped" counts only when `by == "owner"`;
  verified without evidence and dropped by anyone else never count, nor do open and built;
- met: every id counts ("all of the ranked items verified or dropped by the owner");
- not met: any id does not; the label says how many count in words: all, most, some, few or none ("some of the
  ranked items verified or dropped by the owner");
- unknown: no ledger is set ("unknown: no ranked ledger set"), it is missing or cannot be read, or it has no
  valid rows ("unknown: the ranked ledger has no rows").

Ids and evidence text are never read into a label or the audit: only the counts (raw opt-in) and words.

## Config

    {"ranked_ledger": "ranked-ledger.jsonl"}

A synthetic ledger (invented ids, one row per line, the newest per id wins):

    {"id": "synthetic-item-a", "status": "verified", "by": "owner", "evidence": "a synthetic receipt"}
    {"id": "synthetic-item-b", "status": "dropped", "by": "owner", "evidence": ""}
    {"id": "synthetic-item-c", "status": "verified", "by": "agent", "evidence": ""}
    {"id": "synthetic-item-d", "status": "dropped", "by": "agent", "evidence": "an agent said so"}

Here a and b count; c (verified without evidence) and d (dropped by an agent) do not, so row ten is not met:
"some of the ranked items verified or dropped by the owner".

## The weekly block

`bin/limitless-scorecard` (when the state dir exists) prints the "North star (self-reported)" block. Its first
bullet is always the self-reported counts line ("6 green, 2 amber, 2 red of 10"). Then come the measured rows, one
line each, `Measured: <words>: <label>`, in the order 1, 2, 3, 4, 5, 6, 7, 8, 10, and after a row whose hand status
is green while its goal is not met, `Row <name> says green but the measurement says not met.` The block keeps its
five lines: the other summary lines give way first, never the counts line; when the measured lines pass the four
lines left, whole rows (a row with its note) are kept in that order and the rest fold into one line, `More
measured rows in limitless_scorecard.` The note only words the gap: the status stays as the person set it.

## The tool field

`limitless_scorecard` carries all nine rows in `measured`: `{n, criterion_words, label: T1, goal}` plus `note`
when a green row's goal is not met. The counts (`counts`) only with the raw opt-in, and only beside a known
label: row one and two their audits' counts; row three `weeks_started, weeks_decided, recent_closed, recent_open,
cycles`; row four `locked, judged, not_judged, needed`; row five sleep coverage's `window_nights, wearable_nights,
proxy_only_nights, unknown_nights, known_nights, wearable_share, target, goal, demo_rows`; row six `deep_min,
block_hours, feed_leak_min, leak_per_block_hour, days_with_data`; row seven `injections, t0_with_opt_in,
t0_without_opt_in, blocked, window_days`; row eight `glide, call_brief, asks, voice_miq, z0_registry, live, set_up,
checks`; row ten `items, verified, owner_dropped, not_counted, open`.
