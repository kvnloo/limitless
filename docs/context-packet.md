# Context packet: the state card for other long-horizon agents, with no raw data

`bin/limitless-context-packet` turns today's state card into one small JSON packet. Another long-horizon agent
can then know the person's state (sleep, readiness, the decision window, the last message, today's habit, and
whether asks are waiting) without reading the state dir and without one raw value. It wraps the card the
`pre_llm_call` hook already builds and does not rebuild it.

```
bin/limitless-context-packet            # dry run: the packet in words; nothing written
bin/limitless-context-packet --json     # dry run: the packet as JSON on stdout (status line on stderr)
bin/limitless-context-packet --write    # also write it to config "context_packet_path" (atomic, 0600)
```

## Schema `limitless.context/1`

```
{"schema": "limitless.context/1",
 "generated_at": "<ISO UTC, e.g. 2030-01-15T12:00:00Z>",
 "rows": [{"key", "words", "modality", "evidence_tier", "age_words"}, ...],
 "window": "<words>",
 "asks": "asks waiting on you" | "no asks on the card"}
```

| Field | What it is |
|---|---|
| `schema` | always `limitless.context/1`; a later shape gets a new name |
| `generated_at` | when the packet was built, ISO UTC; with `schema`, the only string that holds a digit |
| `rows` | one row per state card item, in the card's order: `sleep`, `readiness`, `window`, `owner_message`, `habit_today` |
| `rows[].words` | the item's T1 label (`short`, `low`, `peak`, `wrote recently`, `Done`), else `unknown: <why>` |
| `rows[].modality` | `measured`, `imported`, `proxy`, `self_report` or `messages` (the envelope's own); null when there is no value |
| `rows[].evidence_tier` | `direct`, `indirect`, `stale` or `none`: how the value was obtained, never a score |
| `rows[].age_words` | the item's age in words (`about four hours ago`, `age unknown`), never hours as a number |
| `window` | the decision window's class: `asleep`, `peak`, `trough`, `anytime` or `unknown` (`window.CLASSES`) |
| `asks` | whether the card carries its "asks waiting on you" line; never a count |

## Where it comes from

`limitless/context_packet.py` calls `card.build`, the same builder the `pre_llm_call` hook and
`limitless_card_view` use, with the raw opt-in off, and keeps only its T1 parts: each item of `card.build`'s
`items` (an evidence envelope) becomes one row of whitelisted fields; `window` is the window item's class;
`asks` is read from the card's own lines. The module never opens a state file itself, so the packet can never
hold anything the card did not already compute. The hook's cache, the card's text and its tests are
unchanged.

The rules:

- No digit: no string in the packet holds a digit except `schema` and `generated_at`, and there is no number.
  A row never takes `value` when it holds a digit (the owner item's value is a time: only its T1 label goes
  in), never `raw`, never `age_h`. A reason that would carry a digit (a date, say) becomes `unknown`. A
  value with a digit and no label becomes "known, but held back: no digit-free words for it". A test walks
  every string and key.
- The raw opt-in (`LIMITLESS_RAW_IN_PROMPT=1`) is ignored here: the packet is always T1, whatever the prompt
  card does. A test sets the flag and gets the same packet.
- It writes only with `--write` and config `context_packet_path` set (a relative path is in the state dir):
  a temp file beside the target, mode 0600, fsync, then a rename, so a reader never sees half a packet and a
  failed write leaves the old file and no temp file. With no path set, `--write` says so and writes nothing.
  Without `--write` it is a dry run and writes nothing at all.
- It never prints a path, never sends, never pushes, never starts a job. No score, no count, no clock-time
  rule.
- Exit 0 when done (also with nothing to write), 1 when the write failed (the plain reason), 2 for bad
  arguments.

`limitless-doctor` has one row for it, `export context packet`: `off` while `context_packet_path` is unset,
`live` when the packet there was written within `STALE_H` by its own `generated_at`, else `stale` (not
written yet, older, or not a `limitless.context/1` packet). `--strict` never counts it
([doctor.md](doctor.md)).

## z0

The [z0](https://github.com/kvnloo/z0) registry was searched for a context-packet or z0id format to emit
(commit `3bec07f`). It has no z0id and no person-state packet schema. It names `z0int.context_resolve.v1` (a
retrieval evidence bundle of information needs and source-backed EvidenceRefs) and says schemas live in the
owning repos; z0intelligence's `z0int.context_resolve.v1` and `z0int.state_packet.v0` describe sources and
repo state, not a person's state. So this packet makes no claim of z0 compatibility: it is the plugin's own
small schema, named `limitless.context/1` so a z0-side adapter can map it later.

## A real synthetic run

`python3 -I scripts/context_packet_example.py` copies the synthetic fixture state (`tests/fixtures/state`) to
a temporary dir, sets the raw opt-in to show it is ignored, and runs the real entry point at the fixture
clock: the dry run, `--write` with no path, `--write` with `context_packet_path` set (then the file's mode and
the doctor row), and `--json`. Its output, verbatim (a test checks this block against it):

```text
$ limitless-context-packet
sleep: short (proxy, indirect, about four hours ago)
readiness: low (imported, direct, about four hours ago)
window: peak (proxy, indirect, under an hour ago)
owner_message: unknown: no owner session DBs or beacons: set LIMITLESS_OWNER_DBS or LIMITLESS_OWNER_BEACONS (config "owner_dbs" or "owner_beacons") (no modality, none, age unknown)
habit_today: Done (self_report, direct, about four hours ago)
window: peak
asks: asks waiting on you
dry run: nothing written (run with --write to write the packet to config "context_packet_path")
(exit 0)
$ limitless-context-packet --write
sleep: short (proxy, indirect, about four hours ago)
readiness: low (imported, direct, about four hours ago)
window: peak (proxy, indirect, under an hour ago)
owner_message: unknown: no owner session DBs or beacons: set LIMITLESS_OWNER_DBS or LIMITLESS_OWNER_BEACONS (config "owner_dbs" or "owner_beacons") (no modality, none, age unknown)
habit_today: Done (self_report, direct, about four hours ago)
window: peak
asks: asks waiting on you
no context packet path: set "context_packet_path" in config.json to write the packet; nothing written
(exit 0)
$ limitless-context-packet --write
sleep: short (proxy, indirect, about four hours ago)
readiness: low (imported, direct, about four hours ago)
window: peak (proxy, indirect, under an hour ago)
owner_message: unknown: no owner session DBs or beacons: set LIMITLESS_OWNER_DBS or LIMITLESS_OWNER_BEACONS (config "owner_dbs" or "owner_beacons") (no modality, none, age unknown)
habit_today: Done (self_report, direct, about four hours ago)
window: peak
asks: asks waiting on you
written: the context packet (config "context_packet_path")
(exit 0)
$ stat -c %a context-packet.json
600
$ limitless-doctor | grep 'context packet'
export context packet: live: written under an hour ago
$ limitless-context-packet --json
{
  "schema": "limitless.context/1",
  "generated_at": "2030-01-15T12:00:00Z",
  "rows": [
    {
      "key": "sleep",
      "words": "short",
      "modality": "proxy",
      "evidence_tier": "indirect",
      "age_words": "about four hours ago"
    },
    {
      "key": "readiness",
      "words": "low",
      "modality": "imported",
      "evidence_tier": "direct",
      "age_words": "about four hours ago"
    },
    {
      "key": "window",
      "words": "peak",
      "modality": "proxy",
      "evidence_tier": "indirect",
      "age_words": "under an hour ago"
    },
    {
      "key": "owner_message",
      "words": "unknown: no owner session DBs or beacons: set LIMITLESS_OWNER_DBS or LIMITLESS_OWNER_BEACONS (config \"owner_dbs\" or \"owner_beacons\")",
      "modality": null,
      "evidence_tier": "none",
      "age_words": "age unknown"
    },
    {
      "key": "habit_today",
      "words": "Done",
      "modality": "self_report",
      "evidence_tier": "direct",
      "age_words": "about four hours ago"
    }
  ],
  "window": "peak",
  "asks": "asks waiting on you"
}
dry run: nothing written (run with --write to write the packet to config "context_packet_path")
(exit 0)
```
