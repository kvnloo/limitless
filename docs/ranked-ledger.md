# The ranked ledger: the only two ways a row enters it

Scorecard row ten reads an optional private ranked ledger ([scorecard-measured.md, row
10](scorecard-measured.md#row-10-top-25-ranked-items-done-verified-or-dropped); `$LIMITLESS_RANKED_LEDGER`, else
config `ranked_ledger`, a relative path in the state dir; the repo ships none). This page is how rows get there.
There are exactly two writers, both in `limitless/ranked_ledger.py` behind `bin/limitless-ranked`:

1. an agent, with evidence: `bin/limitless-ranked add`;
2. the owner, dropping an item by reply: `bin/limitless-ranked ingest`.

Each row is one JSON object per line, `{"id", "status", "by", "evidence"}`, and the newest row per id wins.
The file is append-only: it is opened for append, created mode 0600 (an existing file is set to 0600), held under
an exclusive `flock` for each write, and no old row is ever rewritten. A torn last line is left as it is and the
next row starts on a line of its own. Ids are letters, digits, dot, underscore or dash, at most eighty,
starting with a letter or digit.

## An agent's row: `add`

```bash
bin/limitless-ranked add <id> <open|built|verified> [--evidence TEXT] [--write]
```

It appends `{"id": <id>, "status": <status>, "by": "agent", "evidence": <TEXT or "">}`. There is no way to set
`by`.

- `verified` without a non-empty `--evidence` is refused: exit 2, nothing written.
- `dropped` is refused (exit 2): only the owner drops, by reply. An agent row can never say dropped.
- An item whose newest row is the owner's drop is refused too (exit 2): an agent cannot bring it back.
- Any other status, or a malformed id, is refused (exit 2).
- Without `--write` it is a dry run: it says what it would append and writes nothing. With no ledger set it
  writes nothing and says so (exit 1 with `--write`).

## The owner's drop: `ingest`

```bash
bin/limitless-ranked ingest [--db PATH] [--write]
```

It reads the owner's Telegram messages from the Hermes session DB (read-only; `--db`, else `LIMITLESS_HERMES_DB`,
else config `hermes_db`, as [apps-ingest.md](apps-ingest.md) reads it) after the mark `ranked-drops.json` in the
state dir (with no mark, only the last day, so a first run never acts on an old message). A whole message of the
form

    drop: <id>[, <id>...]

(any case for `drop`, one line, ids comma separated) appends, for each id the ledger already has,

    {"id": <id>, "status": "dropped", "by": "owner", "evidence": "owner reply"}

- unknown ids are ignored and counted; an id the owner already dropped is counted and not appended again;
- every drop message after the mark counts, so a later "thanks" never swallows a drop;
- any other message shape does nothing: "please drop: ...", "drop <id>", a second line, an empty item;
- `--write` appends the rows, then moves the mark to the newest message read. The mark is
  `{"after": <epoch seconds>}` only (no id, no text), written atomically, mode 0600. Without `--write` it is a dry
  run and the mark stays.

## The counts: `list`

```bash
bin/limitless-ranked list [--raw]
```

Row ten's own label, then each count as a share of the items in words: all, most, some, few or none. `--raw`
prints the counts (`items, verified, owner_dropped, not_counted, open`) as JSON instead. It is the same rule as
row ten (`scorecard._top_measured`): verified counts only with evidence, dropped only when `by` is the owner.

Output never names an id, evidence text or a path, and every line but `--raw` is digit-free, so it passes the
tier audit. Nothing here sends, starts a job or edits the config file; it never sends a message.

## Doctor

The `ranked ledger` row ([doctor.md](doctor.md)), right after the apps ingest job's row: `off` with no ledger set;
`live` with "rows read: " and row ten's words; `missing` with "broken: " when the ledger is missing, cannot be read
or has no valid row.

## Example (synthetic)

The real output of `python3 -I scripts/ranked_ledger_example.py`: a made-up ledger and a made-up session DB
(`tests/hermes_db_fixture.py`) in a temporary dir, invented ids only.

```text
$ limitless-ranked add synthetic-item-a built
would append one row: status built, by agent, without evidence
dry run: nothing written (--write appends it to the ranked ledger)
$ limitless-ranked add synthetic-item-a built --write
appended one row: status built, by agent, without evidence
$ limitless-ranked add synthetic-item-b open --write
appended one row: status open, by agent, without evidence
$ limitless-ranked add synthetic-item-c open --write
appended one row: status open, by agent, without evidence
$ limitless-ranked add synthetic-item-a verified --write
limitless-ranked: refused: verified needs a non-empty evidence string (--evidence): nothing written
(exit 2)
$ limitless-ranked add synthetic-item-a verified --evidence "a synthetic test run" --write
appended one row: status verified, by agent, with evidence
$ limitless-ranked add synthetic-item-c dropped --write
limitless-ranked: refused: dropped: only the owner drops, by reply: nothing written
(exit 2)
$ limitless-ranked list
ranked ledger: some of the ranked items verified or dropped by the owner
verified with evidence: some
dropped by the owner: none
open or built: most
not counted (verified without evidence, or dropped by someone else): none
$ limitless-ranked ingest
would write: a drop reply from the owner: one to drop, one unknown ignored, no already dropped
ignore: not a drop reply: changes nothing
would append one owner drop row
dry run: nothing written (--write appends to the ranked ledger and moves ranked-drops.json)
$ limitless-ranked ingest --write
write: a drop reply from the owner: one to drop, one unknown ignored, no already dropped
ignore: not a drop reply: changes nothing
appended one owner drop row
$ limitless-ranked list
ranked ledger: most of the ranked items verified or dropped by the owner
verified with evidence: some
dropped by the owner: some
open or built: some
not counted (verified without evidence, or dropped by someone else): none
$ cat ranked-ledger.jsonl
{"id": "synthetic-item-a", "status": "built", "by": "agent", "evidence": ""}
{"id": "synthetic-item-b", "status": "open", "by": "agent", "evidence": ""}
{"id": "synthetic-item-c", "status": "open", "by": "agent", "evidence": ""}
{"id": "synthetic-item-a", "status": "verified", "by": "agent", "evidence": "a synthetic test run"}
{"id": "synthetic-item-b", "status": "dropped", "by": "owner", "evidence": "owner reply"}
```
