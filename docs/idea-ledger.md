# Idea ledger: one official record for every idea

The person asked for a system: their messages, taken and tracked officially. Ideas already arrive in two ways,
as quick captures (`limitless_capture`) and as plain messages that bedtime capture saves instead of starting
work. Both land in `captures.jsonl` through `capture.py`. The idea ledger is the one record they all end up in:
a job appends each new capture to it once, and nothing ever rewrites it. There is no second journal or store.

## Where it lives

The configured file is the one record: `LIMITLESS_IDEA_LEDGER`, else config `idea_ledger` (a relative path is in
the state dir; `StateReader.idea_ledger_path`). Not set: the job does nothing and says "no idea ledger set".
There is no default path, nothing creates a folder for it, and the captures file itself is never the ledger.

## What a row is

`limitless/idea_ledger.py`. `new_rows(captures, ledger_rows, cursor)` returns the captures not yet in the
ledger as rows `{"kind": "idea", "id", "at", "text", "source", "status": "new"}`, oldest first:

- `at`, `text` and `source` are the capture's own (`source` is `hermes` for a quick capture, `bedtime` for a
  saved message). A capture without text or a readable time is skipped.
- `id` is `idea_` plus sixteen hex digits of the sha256 of the normalised text (NFKC, case-folded, whitespace
  collapsed). The same normalised text is one idea, so a re-run appends nothing and the same thought captured
  twice is one row.
- `cursor(ledger_rows)` is the newest idea time already in the ledger; captures at or before it are skipped.
  An idea the person deleted from the ledger in a review is not appended again.

The ledger is append-only for the code: existing rows are never rewritten or reordered. `append(path, rows,
write=False)` is a dry run unless `write`; a write is one `os.write` of whole newline-terminated lines with
`O_APPEND`, and a file it creates is mode 0600.

## The job

`bin/limitless-ledger-append [--write] [--show]` runs `idea_ledger.run`: one plain, digit-free line ("would
append two ideas", "appended two ideas", "no new ideas", "no idea ledger set"), and the idea text only with
`--show`. It exits 1 only when a ledger is set but cannot be written (a missing folder, or the captures file).

It is offered as one schedule card (`schedule_cards.ledger_card`, sender `local`) on the existing `wind_down`
event, ending when Sleep mode goes on: no clock time, a budget of zero and no push. The card is added to
`limitless_schedule` and to host registration only when a ledger is set. It is not a `jobs.SPECS` job, so
`limitless-jobs` never runs it; whoever approves the card runs the command on the event. A capture made after
the wind-down lands on the next night's run.

## Reading it back

- Tool `limitless_ideas`, read-only: `{value: {label}, modality: "self_report", age_h, evidence_tier}`, aged by
  the newest idea row. The label is words only ("a few new ideas this week, none triaged"; one, two, a few,
  several, many). The counts and the idea text appear only under the raw opt-in (`LIMITLESS_RAW_IN_PROMPT=1`).
  No ledger set is `value: null` with the reason.
- Week review: at most one line, "Ideas recorded this week: a few, none triaged.", through `tier_audit.gate`
  (hook `week_review:ideas`); nothing when no ledger is set.

"This week" is the seven days up to now. An idea counts as triaged when the latest row for its id has a status
other than `new`: the person edits or appends that row in their review. The code never triages.

## Never

No second journal or store, no default path, no triage or prioritising by the code (the person triages in a
review), no starting work from an idea, no push of its own, no clock time, and no idea text outside `--show`
or the raw opt-in. Plain messages are read only through bedtime capture; `owner_messages` reads timestamps
and never content.

## Example

`python3 -I scripts/idea_ledger_example.py` (synthetic captures in a temporary state dir, a fixed clock). Its
real output; the script prints the ledger rows without their text:

```text
# no ledger set
$ limitless-ledger-append --write
no idea ledger set
(exit 0)

# ledger set to ideas.jsonl in the state dir
$ limitless-ledger-append
would append three ideas
(exit 0)
$ limitless-ledger-append --write
appended three ideas
(exit 0)
$ limitless-ledger-append --write
no new ideas
(exit 0)

# the ledger (ideas.jsonl)
{"kind": "idea", "id": "idea_40076e6d741601b5", "at": "2033-05-17T19:10:00+00:00", "source": "hermes", "status": "new"}  # text left out
{"kind": "idea", "id": "idea_6e131a0cffcbc8a0", "at": "2033-05-18T21:40:00+00:00", "source": "hermes", "status": "new"}  # text left out
{"kind": "idea", "id": "idea_01a789726a189ada", "at": "2033-05-18T22:30:00+00:00", "source": "bedtime", "status": "new"}  # text left out

# limitless_ideas (no raw opt-in)
{"value": {"label": "a few new ideas this week, none triaged"}, "modality": "self_report", "age_h": 0.5, "evidence_tier": "direct"}

# week review line
Ideas recorded this week: a few, none triaged.

# its schedule card
Schedule "Idea ledger" (when your wind-down starts, at most once; once your wind-down has started): ends when Sleep mode goes on; nothing is sent; it appends the new captures to your idea ledger
```
