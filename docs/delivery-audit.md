# Delivery audit: did the pushes stay useful?

North-star row two: the brief reaches the person on nearly every wake day, at most a handful of pushes a day,
and every push carries one action. `limitless/delivery_audit.py` measures that from kevin-push's own log, so
nobody has to read the log by hand. It is read-only: it reads the log and never changes how it is written,
sends nothing and starts nothing.

## The log and the fields relied on

`bin/kevin-push` appends one row per call (every decision, delivered or not) to its log:

    {"at": whole epoch seconds, "tag": str, "cls": str, "title": str, "body": str, "how": str}

- `"at"`: the row's local day (the plugin's local zone, as the week review uses).
- `"how"`: `"telegram"` only when the transport returned success: a real delivery (`jobs_runner.DELIVERED`
  is the same word). Every other value is not a delivery and never counts: `"log"` (report only),
  `"folded (brief line)"`, `"held (sleep mode)"`, `"log (duplicate)"`, `"log (daily cap)"`,
  `"log (dropped)"`, `"log (already sent for this event)"`, `"log (quiet: ...)"`, `"log (telegram rc=N)"`.
- `"title"`: the wake brief is the row titled `Wake-up brief` (`jobs.WAKE_BRIEF.send_title`, the title both
  `bin/limitless-brief` and `limitless-jobs` send it under).
- `"body"`: for a delivery, the text as it went out (after `message_shape.fit`), cut to its first 2000
  characters by kevin-push.

These are not in the row, so never used and never guessed: the send gate's decision word itself (only `"how"` is
written), the `--once` event key (kept in `sent.json`, not in the log) and which wake event a brief was for.
A brief is matched to a wake day by its local date.

## Rules

- Window: the seven local days up to today. A day with no row at all is unknown, not zero (the log may not
  cover it); its delivered count, cap verdict and brief verdict are `null`.
- Deliveries per day: rows with `"how": "telegram"`.
- Over the cap: more deliveries in a day than config `push_cap` (a whole number, at least one), else the send
  gate's own `send_gate.DAILY_CAP`. No second number is kept here. (The send gate counts a rolling day; this
  audit counts local days, so a day can show over the cap even when the gate never refused one.)
- Wake days: the local dates of the wake events the plugin already merges (`jobs_runner.events`,
  `jobs.wake_times`: Sleep mode, screen-event wakes, `events.jsonl`): no clock time, no time-of-day rule. A wake
  day is judged only when the log has a row that day; no wake event known is "brief: unknown".
- Reply line: a delivered body has one when its closing line (the last line before any `Why now:` line, never
  the first line) is message_shape's reply line: a `Reply: A / B` choices line or a line with the word reply.
  A body that may have been cut by the log (2000 characters or more) is unknown, not "no reply line".
- Bad lines (not JSON, not an object, no numeric `"at"`, no string `"how"`) are skipped and counted.

The numbers are T0 and stay in the audit dict. The T1 label is words with no digit, joined with "; ":

- push: "within the push limit every day this week", "within the push limit on every logged day",
  "over the push limit on some days", "unknown: no push rows this week";
- brief: "brief reached you on every wake day", "... on most wake days" (more than half), "... on some wake
  days", "brief did not reach you on any wake day", "brief: unknown, no wake days known";
- action: "every push had a reply line", "some pushes had no reply line", "every push with a known body had a
  reply line" (nothing when nothing was delivered).

## Where it shows

- Tool `limitless_delivery`, read-only: `{value: {label}, modality: "measured", age_h, evidence_tier}` with the
  T1 label beside it, aged by the newest row in the window. The counts (per day, the cap, the wake days, the
  pushes with no reply line, skipped lines) appear only with the raw opt-in (`LIMITLESS_RAW_IN_PROMPT=1`, as
  `limitless_body`). Config `push_log` unset is value `null` with the reason "no push log set (config
  push_log)" and the label "unknown: no push log set": unknown, not zero. A missing or unreadable log and a
  week with no row are `null` with a reason too. Reasons never echo the path.
- `limitless-doctor` lists it like every tool: `tool limitless_delivery: off: no push log set (config
  push_log)` until `push_log` is set.
- The week review (`jobs_runner.week_review_body`) carries one line, `Pushes: <words>.`, through
  `tier_audit.gate` (hook `week_review:delivery`); an unknown brief clause is left out, and the line is empty
  when the log is unset, unreadable or has no row in the week.
- The north-star scorecard cites it as row two. `delivery_audit.goal(audit)` judges the audit's own counts:
  "not met" when a logged day went over the cap, a wake day with rows had no delivered brief, or a delivered
  push had no reply line; "met" only when every day of the week has rows, wake days are known (none unknown)
  and every delivered body is known to carry a reply line; anything else is "unknown", and
  unknown is never met. `scorecard.measured` gives `{n, criterion_words, label, goal}` from it (the label above, or the unknown
  words: "unknown: no push log set", "unknown: the push log could not be read", "unknown: no push rows this
  week"). The weekly block (`bin/limitless-scorecard`, when the state dir exists) ends with
  `Measured: delivery: <label>`, plus `Row <name> says green but the measurement says not met.` when the hand
  status of row two is green and the goal is not met; `limitless_scorecard` carries the same in `measured` (counts only
  with the raw opt-in). No status is ever changed by code.

Config (both optional):

    {"push_log": "<kevin-push state dir>/log.jsonl", "push_cap": 6}

A relative `push_log` is in the limitless state dir. There is no default path.

## A real synthetic run

`python3 -I scripts/delivery_audit_example.py` (synthetic rows in kevin-push's shape, three synthetic wake
events, a fixed clock, UTC, a temporary state dir; nothing sent):

```text
# no push log set
{"value": null, "modality": "measured", "age_h": null, "evidence_tier": "none", "reason": "no push log set (config push_log)"}
{"label": "unknown: no push log set", "tier": "T1", "modality": "measured"}

# push_log set (relative: in the state dir); limitless_delivery, no raw opt-in
{"value": {"label": "within the push limit on every logged day; brief reached you on most wake days; some pushes had no reply line"}, "modality": "measured", "age_h": 33.0, "evidence_tier": "stale"}

# the same with the raw opt-in: T0 counts per day (None = no row that day: unknown)
{"day": "2033-05-12", "rows": 0, "delivered": null, "over_cap": null, "wake_day": false, "brief": null, "no_action": 0, "action_unknown": 0}
{"day": "2033-05-13", "rows": 0, "delivered": null, "over_cap": null, "wake_day": false, "brief": null, "no_action": 0, "action_unknown": 0}
{"day": "2033-05-14", "rows": 3, "delivered": 2, "over_cap": false, "wake_day": true, "brief": true, "no_action": 0, "action_unknown": 0}
{"day": "2033-05-15", "rows": 2, "delivered": 0, "over_cap": false, "wake_day": true, "brief": false, "no_action": 0, "action_unknown": 0}
{"day": "2033-05-16", "rows": 0, "delivered": null, "over_cap": null, "wake_day": false, "brief": null, "no_action": 0, "action_unknown": 0}
{"day": "2033-05-17", "rows": 3, "delivered": 2, "over_cap": false, "wake_day": true, "brief": true, "no_action": 2, "action_unknown": 0}
{"day": "2033-05-18", "rows": 0, "delivered": null, "over_cap": null, "wake_day": false, "brief": null, "no_action": 0, "action_unknown": 0}
{"delivered": 4, "known_days": 3, "cap": 6, "over_cap_days": [], "no_action": 2, "action_unknown": 0, "skipped": 1}
{"wake_days": 3, "brief_delivered": 2, "unknown_wake_days": 0, "brief_share": 0.6666666666666666}

# week review line
Pushes: within the push limit on every logged day; brief reached you on most wake days; some pushes had no reply line.

# the log is unchanged: 9 lines
```

On the fifteenth the brief was held by Sleep mode, so that wake day counts as not reached: two of three wake
days, "most". On the seventeenth the brief and the heads-up went out without a reply line.
