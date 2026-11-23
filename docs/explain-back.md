# Explain back: one optional offer after work lands

The ask (LE05): after an agent finishes a piece of work, offer one optional thirty-second explain-back, Feynman
style: "say in one breath what landed and why". It is answered by voice or one tap. It is a suggestion: never a
quiz, never a streak, never a push of its own.

## The offer

`limitless/explain_back.py`. `offer(landed_count, window, already_offered_today)` is the one line

    Explain back: say what landed in one breath. Reply: Voice / Later

or "". The Reply part is `one_tap.choices_line(("Voice", "Later"))`. It offers only when all of these hold:

- something landed since the last offer: a done item in the work queue (config `work_queue_dir`, read by
  `overnight.counts` from file names and mtimes only) newer than the last offer, or newer than last night's
  wind-down (`overnight.since`) when there was none;
- a trough job would deliver now (`decision_window.decide` for a `trough` job): never in a peak, asleep, an
  unknown window, a Glide focus block or focused mode (`modes.apply`), the same window chain the Anki offer uses;
- it was not offered yet for this wake day. The day is keyed on the wake event (`jobs.wake_times`), never a
  clock time. No wake seen, or one older than `window.MAX_AWAKE_H`, is unknown: no offer.

The line goes on the pre_llm_call state card, on a line of its own after the card (outside `MAX_LINES`, so the
Reply choices stay whole), and the card goes through `tier_audit.gate` as always. Once the gate lets that card
through, the hook writes `explain-back.json` in the state dir: `{"wake_at", "offered_at"}` (epoch seconds, mode
0600, never any text). The rest of that wake day carries nothing. There is no new job, no schedule card and no
push: the card only changes what the agent sees on that turn.

## The reply

The agent saves the answer with `limitless_capture` and `kind: "explain_back"` (`explain_back.reply`):

- `Later`, or a bare `Voice` tap, records nothing (skipped is unlogged);
- any other text (the voice transcript, or typed) is one `captures.jsonl` row through `capture.capture`,
  verbatim, with `kind: "explain_back"` and `source: "explain_back"`. Like every capture it lands in the one
  idea ledger when one is set (`docs/idea-ledger.md`);
- `unknowns` holds the person's own "I could not explain X" phrases, verbatim, and only when there are any.
  Nothing else is derived.

The plugin never grades the answer and never asks a follow-up of its own.

## Reading it back

Tool `limitless_explain_back`, read-only: `{value: {offered, answered_this_week}, modality: "self_report",
age_h, evidence_tier}`. `offered` says whether the offer was made for the latest wake event; `answered_this_week`
is words (none, one, two, a few, several, many this week). The T1 label is digit-free, for example
"explain-back offered today; one answered this week". The answers' time, text and unknowns appear only under
the raw opt-in (`LIMITLESS_RAW_IN_PROMPT=1`).

## Never

No scoring, streaks or XP; a skipped offer is unlogged; no push of its own and no job; no clock time; no reply
text outside the raw opt-in.

## Example

`python3 -I scripts/explain_back_example.py` (the repo's synthetic fixture state in a temporary dir, one
synthetic work item, a fixed clock and trough bands). Its real output:

```text
# first trough turn after one item landed
card ends: Explain back: say what landed in one breath. Reply: Voice / Later
mark: ['offered_at', 'wake_at']
# the next turn, same wake event
card ends: asks waiting on you
# a Later tap, and a voice answer (its transcript), each through limitless_capture
$ limitless_capture {"text": "Later", "kind": "explain_back"}
{"age_h": null, "evidence_tier": "none", "modality": null, "reason": "Later: nothing recorded (a skipped explain-back is not logged)", "value": null}
$ limitless_capture {"text": "The synthetic parser now reads the new field and old files still load. I could not explain why the retry waits twice.", "kind": "explain_back"}
{"age_h": 0.0, "evidence_tier": "direct", "label": {"label": "fresh", "modality": "self_report", "tier": "T1"}, "modality": "self_report", "value": {"captured": true, "line": 1}}
captures.jsonl row: kind=explain_back source=explain_back unknowns=['I could not explain why the retry waits twice.']
# read back
$ limitless_explain_back {}
{"age_h": 0.0, "evidence_tier": "direct", "label": {"label": "explain-back offered today; one answered this week", "modality": "self_report", "tier": "T1"}, "modality": "self_report", "value": {"answered_this_week": "one this week", "offered": true}}
$ limitless_explain_back {} (LIMITLESS_RAW_IN_PROMPT=1)
{"age_h": 0.0, "evidence_tier": "direct", "label": {"label": "explain-back offered today; one answered this week", "modality": "self_report", "tier": "T1"}, "modality": "self_report", "value": {"answered_this_week": "one this week", "answers": [{"at": "2030-01-15T12:00:00+00:00", "text": "The synthetic parser now reads the new field and old files still load. I could not explain why the retry waits twice.", "unknowns": ["I could not explain why the retry waits twice."]}], "offered": true}}
# the idea ledger job, with a ledger set
appended one idea
```
