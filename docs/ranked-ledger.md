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

## As an event job

Nobody has to run `ingest` by hand: `limitless-jobs --send` runs the same owner drop-reply ingest once after each
sync run, the apps ingest job's pattern ([apps-ingest.md](apps-ingest.md#as-an-event-job)).

- **When.** Job `ranked_ingest` (`jobs.RANKED_INGEST`) wakes on the `sync` event: a new newest row in `runs.jsonl`
  that has a time in `at` and is not `"ok": false`. It runs at most once per such row; the same row polled again is
  a drop, "already ran after this sync". A failed sync, a row timestamped in the future or no `runs.jsonl` at all is
  `not_triggered`. No clock time, no cron string, no interval.
- **Config `ranked_ingest`.** `off` (the default, and any other value): never due, nothing is read, and
  `limitless-jobs` prints no line for it. `dry_run`: `ranked_ledger.ingest(write=False)`: it reads the owner's
  messages and says what it would append; the ledger and `ranked-drops.json` keep their bytes. `write`:
  `ranked_ledger.ingest(write=True)`, the same append-only owner drop rows and mark move as `ingest --write`.
  `limitless-jobs` without `--send` is a dry run of the runner: the verdict only, nothing read.
- **Inputs.** The ledger is row ten's (`$LIMITLESS_RANKED_LEDGER`, else config `ranked_ledger`) and the DB the
  command's (`LIMITLESS_HERMES_DB`, else config `hermes_db`), read-only. With either unset the job is skipped with
  a plain reason ("skipped: no ranked ledger set ..." or "skipped: no Hermes DB set (config hermes_db)") and
  nothing is read or written.
- **Only the owner drops.** The job is `ranked_ledger.ingest`, nothing more: only whole `drop: <id>[, <id>...]`
  messages from the person (role `user`) count, every appended row is `"by": "owner"`, and an agent row is never
  made dropped through this path (an assistant line that says "drop: ..." changes nothing).
- **The status file `ranked-ingest.json`** (in the state dir, atomic, 0600) records the last pass: `row_at` (epoch
  seconds of the `runs.jsonl` row it acted on), `ran_at` (epoch seconds of the pass), `mode` and `action`, one of
  `nothing` (no new owner message), `ignore` (no owner drop to append), `would write` or `write`. Never an id,
  evidence or message text, and no digit outside the two epoch values. It is separate from `ranked-drops.json`,
  which only `write` moves.
- **Sends nothing.** No push, no decision window, quiet or send gate, nothing appended to `jobs-sent.jsonl`, so it
  also runs while you sleep. It never sends a message, and it never restarts, kills or starts a process.
- **Schedule card.** With `ranked_ingest` on, `limitless_schedule` and the host registration add one card
  (`schedule_cards.ranked_ingest_card`, id `ranked_ingest`, sender `local`, budget zero, once-key
  `ranked_ingest:<sync run time>`) on the trigger "after each sync run", never a clock.
- **Doctor.** One `job ranked ingest` row, right after the `ranked ledger` row: `off` by config; `missing` with
  "broken: " when it is on but no ranked ledger or no Hermes DB is set, or the ledger is missing or cannot be read;
  `stale` before any sync run or while the newest sync is one it has not run after; else `live`, with the mode,
  the pass's age and its result in words ("appended owner drop rows", "would append owner drop rows", "no owner
  drop to append", "no new owner message"). Never an id, never a digit. `--strict` never counts this row.

### Synthetic example

`python3 -I scripts/ranked_ingest_job_example.py` (a made-up ledger, a made-up session DB and made-up `runs.jsonl`
rows in a temp dir, invented ids only; real output):

```text
# config {"ranked_ledger": "ranked-ledger.jsonl", "hermes_db": "hermes.db"}
runs.jsonl += {"at": "2030-01-06T06:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the ranked ingest's line)
(no ranked ingest line)

# config {"ranked_ledger": "ranked-ledger.jsonl", "ranked_ingest": "write"}
$ limitless-jobs --send   (the ranked ingest's line)
Ranked ingest: not_triggered: skipped: no Hermes DB set (config hermes_db)

$ limitless-doctor   (the job row)
job ranked ingest: missing: broken: on (write mode), but no Hermes DB set (config hermes_db)

# config {"ranked_ledger": "ranked-ledger.jsonl", "hermes_db": "hermes.db", "ranked_ingest": "dry_run"}
$ limitless-jobs --send   (the ranked ingest's line)
Ranked ingest: run: a sync ran; would append one owner drop row (config ranked_ingest "write" appends it)

ledger unchanged after the dry run: True; ranked-drops.json exists: False

$ limitless-ranked list
ranked ledger: none of the ranked items verified or dropped by the owner
verified with evidence: none
dropped by the owner: none
open or built: all
not counted (verified without evidence, or dropped by someone else): none

# config {"ranked_ledger": "ranked-ledger.jsonl", "hermes_db": "hermes.db", "ranked_ingest": "write"}
runs.jsonl += {"at": "2030-01-06T07:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the ranked ingest's line)
Ranked ingest: run: a sync ran; appended one owner drop row

$ limitless-ranked list
ranked ledger: some of the ranked items verified or dropped by the owner
verified with evidence: none
dropped by the owner: some
open or built: some
not counted (verified without evidence, or dropped by someone else): none

# the same sync row, polled again
$ limitless-jobs --send   (the ranked ingest's line)
Ranked ingest: drop: already ran after this sync

# the next sync, with no new owner message
runs.jsonl += {"at": "2030-01-06T08:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the ranked ingest's line)
Ranked ingest: run: a sync ran; no new owner message: the ranked ledger stays as it is

ranked-ingest.json (mode 0o600):
{"action": "nothing", "mode": "write", "ran_at": 1893916860.0, "row_at": 1893916800.0}
newest rows by: dropped by owner, open by agent

$ limitless-doctor   (the job row)
job ranked ingest: live: write mode: ran under an hour ago after a sync: no new owner message

schedule card:
Schedule "Ranked ingest" (after each sync run, at most once; asleep or awake: it sends nothing, so no window holds it): ends at the next sync run; nothing is sent; it reads your drop replies and, in write mode, marks those ranked items dropped by you in the ranked ledger
files in the state dir: hermes.db, ranked-drops.json, ranked-ingest.json, ranked-ledger.jsonl, runs.jsonl
```

## Doctor

The `ranked ledger` row ([doctor.md](doctor.md)), right after the apps ingest job's row: `off` with no ledger set;
`live` with "rows read: " and row ten's words; `missing` with "broken: " when the ledger is missing, cannot be read
or has no valid row.
The `job ranked ingest` row follows it ([above](#as-an-event-job)).

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
