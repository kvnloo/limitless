# Scorecard: what code measured

The north-star scorecard (`limitless/scorecard.py`) is a hand-kept Markdown table: the person sets each row's
status (red, amber, green). Code never reads the evidence column and never changes a status. Beside the hand
status it says, in words, what code measured for the rows it can measure from data the plugin already writes.

    scorecard.measured_audits(state_dir, cfg, now, tz)  -> [(row, audit)] for rows 1, 2, 3, 4 and 7
    scorecard.measured(state_dir, cfg, now, tz)         -> [{n, criterion_words, label, goal}]
    scorecard.measured_lines(rows, measured)            -> the weekly block's measured lines (at most five)

`label` is digit-free T1 words, or `unknown: <why>`; `goal` is met, not met or unknown, and unknown is never
met. A missing, torn or unreadable file is unknown, never an error. Read-only: nothing is written or sent, no
second store is kept, and code never marks a row green.

## The five measured rows

| Row | Words | Read from |
|---|---|---|
| 1 | loop uptime | the uptime audit of the sync's `runs.jsonl` ([uptime-audit.md](uptime-audit.md)) |
| 2 | delivery | the delivery audit of kevin-push's log, config `push_log` ([delivery-audit.md](delivery-audit.md)) |
| 3 | habit loop | the stop rule's loop rows in `predictions.jsonl` and the habit files ([stop-rule.md](stop-rule.md)) |
| 4 | evidence loop | the locks and receipts in `predictions.jsonl` ([experiment.md](experiment.md)) |
| 7 | privacy | `tier_audit.check` over the tier audit log ([privacy-tiers.md](privacy-tiers.md)) |

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

### Row 7, "Privacy: no raw health data above T1, 0 leaks"

`tier_audit.check` over the configured audit log (`$LIMITLESS_AUDIT`, else config `audit_path`) for the last
seven days:

- met: the log has rows in the window and nothing digit-bearing (a card or a tool result) went out without the
  opt-in; blocked rows are fine: they were stopped, never sent;
- not met: one went out without the opt-in (a T0 row that is not blocked and has no opt-in);
- unknown: no audit log is set ("unknown: no audit log set") or it has no rows in the window ("unknown: no
  audit rows this week").

## The weekly block

`bin/limitless-scorecard` (when the state dir exists) ends the "North star (self-reported)" block with one line
per measured row, `Measured: <words>: <label>`, in the order 1, 2, 3, 4, 7, and after a row whose hand status is
green while its goal is not met, `Row <name> says green but the measurement says not met.` The block keeps its
five lines: summary lines give way first; when the measured lines alone pass five, whole rows are kept in that
order and the rest fold into one line, `More measured rows in limitless_scorecard.` The note only words the gap:
the status stays as the person set it.

## The tool field

`limitless_scorecard` carries all five rows in `measured`: `{n, criterion_words, label: T1, goal}` plus `note`
when a green row's goal is not met. The counts (`counts`) only with the raw opt-in, and only beside a known
label: row three `weeks_started, weeks_decided, recent_closed, recent_open, cycles`; row four `locked, judged,
not_judged, needed`; row seven `injections, t0_with_opt_in, t0_without_opt_in, blocked, window_days`.
