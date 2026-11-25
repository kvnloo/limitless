# Delivery ledger (design draft, for review)

Status: a schema and its core moves, for outside review before anything is built on it. Nothing is wired
yet: `bin/kevin-push` and `limitless/jobs_runner.py` still keep `sent.json` and `held.jsonl`, and nothing reads
or writes this ledger. Reference code: `limitless/delivery_ledger.py` (stdlib `sqlite3`, Python 3.9+), tests in
`tests/test_delivery_ledger.py` (synthetic targets only).

## Why

Today the budget is a rolling 24 h count in `send_gate.decide` over `sent.json`. `kevin-push` reads the file,
decides, sends and writes the whole file back with no lock, so two senders at once can both see the last slot
free, and a message that was held lives in a second file (`held.jsonl`). A move between two files can be split
by a crash. The jobs runner already counts a send only after a real delivery; the ledger keeps that rule and
makes the check and the claim of a slot one step.

## Shape

- ONE table, one row per message to one target, a `state` column.
- Every move is one `UPDATE delivery SET state = ? ... WHERE id = ? AND state = ?`. An update that changes no
  row was not allowed from the row's state: the code raises `IllegalTransition`. There is no move between two
  tables for a crash to split.
- The budget check and the insert of the `queued` row run in ONE `BEGIN IMMEDIATE` transaction (the slot is
  reserved at check time). The move held -> queued does the same.
- No clock is read. The caller passes `now` and `day_start` (epoch seconds).

## Schema

```sql
CREATE TABLE IF NOT EXISTS delivery (
    id            INTEGER PRIMARY KEY,
    target        TEXT NOT NULL,   -- platform:chat_id:thread_id
    job_id        TEXT,
    dedup_key     TEXT,
    window_class  TEXT NOT NULL CHECK (window_class IN ('peak', 'anytime', 'trough', 'bypass')),
    state         TEXT NOT NULL CHECK (state IN ('held', 'queued', 'sent', 'failed', 'unknown', 'expired')),
    reason        TEXT CHECK (reason IN ('cap', 'quiet', 'sleep', 'dedup', 'failed')),
    body          TEXT NOT NULL,
    created_at    REAL NOT NULL,
    release_after REAL,
    sent_at       REAL,
    reserved_at   REAL,            -- when the row took its budget slot; set exactly while it holds one
    CHECK ((state IN ('queued', 'sent', 'unknown')) = (reserved_at IS NOT NULL)),
    CHECK (state <> 'held' OR reason IS NOT NULL),
    CHECK (state <> 'sent' OR sent_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS delivery_target_state_created ON delivery (target, state, created_at);
```

Two additions to the agreed column list, both open for review below:

- `reserved_at`: the time the row took its slot. The budget counts on it, not on `created_at`, so a row held
  yesterday and released today counts today, and a failed row (slot freed) stops counting at once.
- reason `failed`: the reason on a held row that came back from a failed send.

The target is `platform:chat_id:thread_id`; the thread may be empty (`telegram:example-chat:`), the platform and
chat may not.

## States and moves

Only these moves exist; anything else raises `IllegalTransition`.

```text
 reserve() --+--> queued --mark_sent()-----> sent      (keeps its slot)
             |      |  \---mark_unknown()--> unknown   (keeps its slot, never replayed)
             |      |
             |      \---mark_failed()------> held (reason failed, slot freed)
             |                                 |
             \--> held (cap|quiet|sleep|dedup) +--release()--> queued   (budget checked again)
                                               \--expire_old()--> expired (counted, never deleted)
```

| from | to | call | slot |
| --- | --- | --- | --- |
| (new) | `queued` | `reserve` | taken |
| (new) | `held` | `reserve` (dedup, quiet, sleep, cap) | none |
| `queued` | `sent` | `mark_sent(id, now)` | kept |
| `queued` | `unknown` | `mark_unknown(id)` | kept; no move leaves `unknown` |
| `queued` | `held` (reason `failed`) | `mark_failed(id, release_after)` | freed |
| `held` | `queued` | `release(id, day_start, now, cap)` | taken, or stays held with reason `cap` |
| `held` | `expired` | `expire_old(now, max_age_s)` | none |

`sent`, `unknown` and `expired` are final. `failed` is in the state list as agreed, but no move writes it in this
draft (see the open questions). A dedup hold never comes due and can only expire.

## The budget

```sql
SELECT COUNT(*) FROM delivery
 WHERE target = ? AND state IN ('queued', 'sent', 'unknown')
   AND window_class <> 'bypass' AND reserved_at >= ?   -- ? = day_start
```

- The budget day refills on a day boundary the caller gives (`day_start`: a local midnight or the wake event),
  never a rolling 24 h.
- `reserve` decides in this order: a `dedup_key` already `queued`, `sent` or `unknown` for the target since
  `day_start` holds with reason `dedup`; the caller's `hold` (`quiet` or `sleep`) holds with that reason; no slot
  holds with reason `cap`; else `queued`.
- `peak` gets one reserved last token: `anytime` and `trough` may fill only `cap - 1` slots, `peak` may fill all
  `cap`. A decision never borrows from tomorrow, so "shares an N-a-day budget" stays true. The default cap is
  `send_gate.DAILY_CAP` (six).
- `failed` frees its slot; `unknown` (the transport may have delivered) keeps it.

## Held rows

Held rows leave by one of three ways, and never silently:

1. (a) as one digest riding the next allowed message (not in this draft: see the open questions);
2. (b) a periodic pass: `due_held(now)` lists held rows whose `release_after` has passed, oldest first, and
   `release` moves each to `queued` if the budget has a slot;
3. (c) after the max hold age, `expire_old(now, max_age_s)` moves them to `expired` and returns the count for
   one count line ("N held messages expired"). No row is ever deleted.

## Bypass

A `bypass` row is recorded like any other but never takes a budget slot and is never held for `cap`. It is for:

- failure alerts, which are already rate-limited where they are raised;
- schedule and change cards (the owner asked to see them);
- one-shot messages the user scheduled;
- replies to a message the user sent.

`dedup` and the caller's `quiet` or `sleep` hold still apply to a bypass row.

## Open questions for review

- Digest body cap: how many held rows, or characters, ride one digest before the rest wait for the next
  message? (`held.jsonl` keeps a body to 1000 characters; the message shape keeps a push to six lines.)
- Max hold age default for `expire_old`: 12 h (the send gate's dedupe span), one budget day, or per window
  class?
- What a bypass counts against: nothing (this draft), its own small cap, or the day budget once it is spent?
- A held row folded into a digest: does it become `sent` with the carrier's `sent_at` and no `reserved_at` (so
  it takes no slot of its own), or does it need its own state?
- `failed` as a resting state: this draft goes queued -> held (reason `failed`) in one move, so no row ever
  sits in `failed`. Keep the state for a permanent failure (no sender), or drop it?
- `reserved_at`: is one more column acceptable, or should the budget count on `created_at` and a release
  insert a new row instead?
- Dedup span: the current budget day (this draft), 12 h, or forever for event keys such as
  `wake_brief:<event time>`? Should a second copy of a message that is already held also be held as `dedup`?
- `unknown` -> `sent` when the transport later confirms: allow it (the slot is the same), or keep `unknown`
  final?
- `wind_down` (a window class in `docs/decision-window.md`) is not in the ledger's list: map it to `anytime`?
