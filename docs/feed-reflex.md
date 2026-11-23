# Feed reflex

The habit catalogue's feeds-free first hour has a sibling: a circuit breaker for opening a feed straight from
unlocking the phone. `limitless/feed_reflex.py` measures that reflex, a feed app as the first thing opened after an
unlock, and says it in words. It only observes and suggests: it never blocks, closes or delays an app, and it has no
intervention engine. The person decides.

## Inputs

- **Unlocks**: the phone's ActivityWatch DB copy (config `aw_db` or `LIMITLESS_AW_DB`), bucket type
  `os.lockscreen.unlocks`, read by `aw_reader.person_rows` as `KEYGUARD_HIDDEN` rows. Opened read-only.
- **App rows**: the same DB's app-in-foreground rows (`blocks.read_rows`), labelled source `phone`. Desktop rows
  (`aw_desktop`, `blocks.source_rows` source `desktop`) never count, and the desktop's ActivityWatch is never read.
- **Feed apps**: the person's own list, `feeds_evidence.feed_apps` (`LIMITLESS_FEED_APPS`, else config
  `feed_apps`), names trimmed and case-folded. The repo ships no list of app names.

## Rule

- `reflex(unlocks, rows, feed_apps, gap_s=REFLEX_GAP_S)` takes each unlock, finds the first phone row starting at
  or after it and before the next unlock, and counts the unlock as a reflex when that row starts within `gap_s`
  of the unlock and its app is a feed app. A non-feed app first, then a feed, does not count. An app opened after
  the gap does not count. It gives per-day counts (`days`: `{day, unlocks, feed_first}`) and the totals.
- The gap is config `feed_reflex_gap_s`, default `REFLEX_GAP_S` (thirty seconds). It is a duration from the
  unlock, never a clock time. Days are local calendar days only to group the counts.
- An unlock whose gap the phone data has not covered yet (the newest phone row ends inside it) is left out, not
  counted as no feed.
- Unknown is never zero. No feed apps set, no readable DB, no unlock or no phone app row is unknown with a plain
  reason, and so are fewer unlocks than `feed_reflex_min_unlocks` (default `MIN_UNLOCKS`, five): "unknown: too
  few unlocks to say".

## Words

`label` gives the T1 words, digit-free:

- "a feed was often the first thing opened after unlocking", from `feed_reflex_often_share` (default
  `OFTEN_SHARE`, a half) of the unlocks;
- "a feed was rarely the first thing opened after unlocking", under `feed_reflex_rarely_share` (default
  `RARELY_SHARE`, a fifth);
- "a feed was sometimes the first thing opened after unlocking" in between;
- "unknown: <why>" otherwise.

The thresholds are shares of the person's own unlocks and change the wording only. The counts are T0: the tool's
value has them only under the raw opt-in (`LIMITLESS_RAW_IN_PROMPT=1`), the same rule as every other tool.

## Where it shows

- **`limitless_feed_reflex`**: the last seven days (`LOOKBACK_DAYS`) as `{value, modality: "proxy", age_h,
  evidence_tier}` with the T1 label. An app opened first is not a feed read, so it is a proxy, aged by the newest
  phone row or unlock. Unknown is `value: null` with the reason.
- **The week review**: one optional line after the flow-metrics line, "Phone: a feed was often the first thing
  opened after unlocking this week.", for the habit week (`jobs_runner.week_feed_reflex`, through
  `tier_audit.gate`, hook `week_review:feed_reflex`). There is no line when it is unknown.
- **The habit catalogue**: when the reflex is "often" and the feeds-free first hour is not running, the existing
  "Next up, if you want it: ..." line after a Drop (and `limitless_habit_next`) may name
  `habit_catalogue.CIRCUIT_BREAKER`, "Circuit breaker after unlocking". It sits outside the ordered list of
  eight, so nothing else changes. Once the person has run, kept or dropped it, it is not offered again. It only
  suggests: no habit starts without the person's yes and `habit_start`.
- **`limitless-doctor`**: a `feed reflex` row after the desktop AW row: off with no feed apps, live when it can say,
  unknown (status missing) with the reason. It is words only and never shows the words it would say.

It has no score, no streak and no target. Nothing is written or sent.

## Synthetic run

`python3 -I scripts/feed_reflex_example.py` builds made-up DBs in a temporary dir: two unlocks a day for six days,
with the feed first on every other unlock, or on one in twelve; the other unlocks open the feed after the gap, or
a notes app first.

```text
## no feed_apps set
{"age_h": null, "evidence_tier": "none", "label": {"label": "unknown: no feed apps set (config feed_apps)", "modality": "proxy", "tier": "T1"}, "modality": "proxy", "reason": "feed reflex unknown: no feed apps set (config feed_apps)", "value": null}
## feed_apps set, no aw_db
{"age_h": null, "evidence_tier": "none", "label": {"label": "unknown: no readable ActivityWatch DB (aw_db)", "modality": "proxy", "tier": "T1"}, "modality": "proxy", "reason": "feed reflex unknown: no readable ActivityWatch DB (aw_db)", "value": null}
## too few unlocks
{"age_h": null, "evidence_tier": "none", "label": {"label": "unknown: too few unlocks to say", "modality": "proxy", "tier": "T1"}, "modality": "proxy", "reason": "feed reflex unknown: too few unlocks to say", "value": null}
## a feed first on every other unlock
{"age_h": 5.9, "evidence_tier": "indirect", "label": {"label": "a feed was often the first thing opened after unlocking", "modality": "proxy", "tier": "T1"}, "modality": "proxy", "value": {"label": "a feed was often the first thing opened after unlocking"}}
## the same, with the raw opt-in
{"age_h": 5.9, "evidence_tier": "indirect", "label": {"label": "a feed was often the first thing opened after unlocking", "modality": "proxy", "tier": "T1"}, "modality": "proxy", "value": {"days": [{"day": "2030-01-23", "feed_first": 1, "unlocks": 2}, {"day": "2030-01-24", "feed_first": 1, "unlocks": 2}, {"day": "2030-01-25", "feed_first": 1, "unlocks": 2}, {"day": "2030-01-26", "feed_first": 1, "unlocks": 2}, {"day": "2030-01-27", "feed_first": 1, "unlocks": 2}, {"day": "2030-01-28", "feed_first": 1, "unlocks": 2}], "feed_first": 6, "gap_s": 30.0, "label": "a feed was often the first thing opened after unlocking", "unlocks": 12}}
## a feed first on one unlock in twelve
{"age_h": 5.9, "evidence_tier": "indirect", "label": {"label": "a feed was rarely the first thing opened after unlocking", "modality": "proxy", "tier": "T1"}, "modality": "proxy", "value": {"label": "a feed was rarely the first thing opened after unlocking"}}
## a wider gap (feed_reflex_gap_s: a duration)
{"age_h": 5.9, "evidence_tier": "indirect", "label": {"label": "a feed was often the first thing opened after unlocking", "modality": "proxy", "tier": "T1"}, "modality": "proxy", "value": {"label": "a feed was often the first thing opened after unlocking"}}
## week review line
Phone: a feed was often the first thing opened after unlocking this week.
## Next up after a Drop, the reflex often
Next up, if you want it: Circuit breaker after unlocking.
## Next up after a Drop, no feed_apps
Next up, if you want it: Feeds-free first hour.
## doctor rows
feed reflex: off: no feed apps set (config feed_apps)
feed reflex: missing: unknown: no readable ActivityWatch DB (aw_db)
feed reflex: missing: unknown: too few unlocks to say
feed reflex: live: reads unlocks and phone app rows from the last week
## circuit breaker entry
{"cue": "habit_cue", "environment": "feed apps moved off the home screen", "id": "feed_circuit_breaker", "layer": "foundation", "name": "Circuit breaker after unlocking", "start": "when a feed opens straight after unlocking, close it and name one thing you came to do"}
```
