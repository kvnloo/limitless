# Work apps and feed apps from one reply

Deep work, focus blocks, the break nudge, flow metrics and the flow ledger need the person's work apps
(`flow_work_apps`); the feed reflex, the feed leak and the first-hour feeds hint need their feed apps
(`feed_apps`). Both ship empty, so every one of those answers unknown until a list is set. The person can set
either list with one Telegram reply instead of editing the config file.

`limitless/apps_reply.py` reads the reply; `bin/limitless-apps-ingest` writes it to `apps.json` in the state
dir. It is the `bin/limitless-quiet-ingest` shape ([quiet.md](quiet.md)).

## The reply

| Whole message (any case) | Does |
| --- | --- |
| `work apps: editorapp, termapp` | sets the work list |
| `feed apps: scrollapp, clipapp` | sets the feed list |
| `work apps: editorapp` and, on the next line, `feed apps: scrollapp` | sets both |
| `work apps:` then one name per line | the same as commas |
| `work apps: none` (or `feed apps: none`) | clears that list |

- Names are comma or newline separated, trimmed and de-duplicated (any case; the first spelling is kept).
- At most twenty names per list, each at most sixty characters; over either limit, the message changes nothing.
- The message must start with `work apps:` or `feed apps:`. Anything else changes nothing: "my work apps are
  editorapp", "work apps please", an empty list or the same list twice in one message.
- Per list, the newest reply wins. A reply that names only one list keeps the other as it was.

## The command

```bash
bin/limitless-apps-ingest [--db PATH] [--write]
```

The Hermes session DB (`--db`, `LIMITLESS_HERMES_DB` or config `hermes_db`; no default) is opened read-only
and the person's Telegram messages after `apps.json`'s `since` are read (with no `apps.json`, only the last
day, so a first run never acts on an old message). With `--write` it writes `apps.json`,
`{"since", "work_apps", "feed_apps"}`, atomically (a temp file in the state dir, mode 0600, then a rename),
`since` being the newest command's reply time. Without `--write` it is a dry run: it prints what it would
write and writes nothing. It never edits the config file, starts nothing and sends nothing. The rows name
which list a message set, never the reply text; the one line with names is what it writes, shown to whoever
runs it.

## Which list wins

One helper, `apps_reply.list_for`, is used by `flow_week.work_apps`, `feeds_evidence.feed_apps` and the feed
reflex (so blocks, the break nudge, flow metrics and the flow ledger too). For each list:

1. the env: `LIMITLESS_FLOW_WORK_APPS` / `LIMITLESS_FEED_APPS` (comma lists);
2. else the config: `flow_work_apps` / `feed_apps` (a list or a comma string);
3. else `apps.json`, set from a reply.

A list set in config wins over a reply, always: config wins, and a reply cannot change it. An empty value
at one step falls through to the next. A missing or broken `apps.json` is no list.

## Doctor

The `apps lists` row ([doctor.md](doctor.md)), right after the feed reflex row: `off` when neither list is
set; otherwise `live`, saying for each list "set from the environment", "set from config", "set from a reply"
or "not set". It never shows an app name or a count, and neither does any tool label.

## Synthetic run

`python3 -I scripts/apps_ingest_example.py` (a temporary Hermes-shaped DB, made-up app names, a fixed time):

```text
## doctor row before any reply
apps lists: off: no work apps or feed apps set (config flow_work_apps, feed_apps, or a reply)
## a dry run, then --write
$ limitless-apps-ingest
2030-03-17T17:31:40+00:00: ignore: not work apps or feed apps: changes nothing
2030-03-17T17:36:40+00:00: would write: work apps: the newest reply for these lists
2030-03-17T17:41:40+00:00: would write: feed apps: the newest reply for these lists
would write apps.json: {"since": "2030-03-17T17:41:40+00:00", "work_apps": ["editorapp", "termapp", "notesapp"], "feed_apps": ["scrollapp"]}
dry run: nothing written (--write writes apps.json)
$ limitless-apps-ingest --write
2030-03-17T17:31:40+00:00: ignore: not work apps or feed apps: changes nothing
2030-03-17T17:36:40+00:00: write: work apps: the newest reply for these lists
2030-03-17T17:41:40+00:00: write: feed apps: the newest reply for these lists
wrote apps.json: {"since": "2030-03-17T17:41:40+00:00", "work_apps": ["editorapp", "termapp", "notesapp"], "feed_apps": ["scrollapp"]}
## apps.json (mode 600)
{"since": "2030-03-17T17:41:40+00:00", "work_apps": ["editorapp", "termapp", "notesapp"], "feed_apps": ["scrollapp"]}
apps lists: live: work apps set from a reply; feed apps set from a reply
## a second run reads only newer messages
$ limitless-apps-ingest --write
no reply: nothing: no new message: the app lists stay as they are
## work apps: none clears the work list
$ limitless-apps-ingest --write
2030-03-17T17:48:40+00:00: write: work apps: the newest reply for these lists
2030-03-17T17:48:50+00:00: ignore: not work apps or feed apps: changes nothing
wrote apps.json: {"since": "2030-03-17T17:48:40+00:00", "work_apps": [], "feed_apps": ["scrollapp"]}
{"since": "2030-03-17T17:48:40+00:00", "work_apps": [], "feed_apps": ["scrollapp"]}
apps lists: live: work apps not set; feed apps set from a reply
## config wins over the reply
apps lists: live: work apps not set; feed apps set from config
(('cfgfeedapp',), 'config')
```

## As an event job

Nobody has to run the command: `limitless-jobs --send` runs the same ingest once after each sync run, the NOOP
export job's pattern ([noop-export.md](noop-export.md#as-an-event-job)).

- **When.** Job `apps_ingest` (`jobs.APPS_INGEST`) wakes on the `sync` event: a new newest row in `runs.jsonl`
  that has a time in `at` and is not `"ok": false`. It is due once per such row; the same row polled again is a
  drop, "already ran after this sync". A failed sync, a row timestamped in the future or no `runs.jsonl` at all is
  `not_triggered`. No clock time, no cron string, no interval.
- **Config `apps_ingest`.** `off` (the default, and any other value): never due, and `limitless-jobs` prints no
  line for it. `dry_run`: reads the replies and records "would write" in the mark; `apps.json` is not written.
  `write`: the same atomic 0600 write of `apps.json` as `--write` (newest reply per list wins, config still
  wins over it). `limitless-jobs` without `--send` is a dry run of the runner: the verdict only, nothing read.
- **The DB.** The same Hermes session DB as the command: `LIMITLESS_HERMES_DB`, else config `hermes_db` (a
  relative path is in the state dir), read-only. With neither set the job is skipped with a plain reason,
  "skipped: no Hermes DB set (config hermes_db)", and nothing is read or written.
- **The mark `apps-ingest.json`** (in the state dir, atomic, 0600): `row_at` (epoch seconds of the `runs.jsonl`
  row it acted on), `ran_at` (epoch seconds of the run), `mode` and `action`, one of `nothing`, `would write` or
  `write`. A run that writes also records `wrote_at` (epoch seconds of that run) and `wrote`, the words of the
  lists it set (`work`, `feed`); a later run that writes nothing keeps both, so the next wake brief can still
  tell that write once ([below](#told-once-in-the-wake-brief)). Never an app name, never reply text, no digit
  outside the epoch values.
- **The T1 line.** When a run writes the app lists, its row carries one plain line, "app lists set from your
  reply" (`jobs.APPS_LINE`), and `jobs_runner.apps_ingest_label(state_dir)` returns it as a T1 label until the
  next run, so a later wake brief may show it. The job itself never sends: no push, no decision window, quiet or
  send gate, nothing appended to `jobs-sent.jsonl`, so it also runs while you sleep.
  It never restarts, kills or starts a process.
- **Schedule card.** With `apps_ingest` on, `limitless_schedule` and the host registration add one card
  (`schedule_cards.apps_ingest_card`, sender `local`, budget zero) on the trigger "after each sync run".
- **Doctor.** One `job apps ingest` row, right after the `apps lists` row: `off` by config; `stale` with no Hermes
  DB set, before any sync run, or while the newest sync is one it has not run after; else `live`, with the mode,
  the run's age and what it did in words ("wrote the app lists", "would write the app lists", "no new apps
  reply"). Never an app name, never a digit. `--strict` never counts this row.

### Synthetic example

`python3 -I scripts/apps_ingest_job_example.py` (a made-up session DB and made-up `runs.jsonl` rows in a temp dir;
real output):

```text
# config {"hermes_db": "hermes.db"}
runs.jsonl += {"at": "2030-01-06T06:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the apps ingest's line)
(no apps ingest line)

# config {"apps_ingest": "write"}
$ limitless-jobs --send   (the apps ingest's line)
Apps ingest: not_triggered: skipped: no Hermes DB set (config hermes_db)

$ limitless-doctor   (the job row)
job apps ingest: stale: on (write mode), but skipped: no Hermes DB set (config hermes_db)

# config {"hermes_db": "hermes.db", "apps_ingest": "dry_run"}
$ limitless-jobs --send   (the apps ingest's line)
Apps ingest: run: a sync ran; would write the app lists (config apps_ingest "write" writes them)

apps.json exists after the dry run: False

# config {"hermes_db": "hermes.db", "apps_ingest": "write"}
runs.jsonl += {"at": "2030-01-06T07:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the apps ingest's line)
Apps ingest: run: a sync ran; wrote the app lists
T1 line for a later brief: app lists set from your reply

# the same sync row, polled again
$ limitless-jobs --send   (the apps ingest's line)
Apps ingest: drop: already ran after this sync

# the next sync, with no new reply
runs.jsonl += {"at": "2030-01-06T08:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the apps ingest's line)
Apps ingest: run: a sync ran; no new apps reply: the app lists stay as they are

apps-ingest.json (mode 0o600):
{"action": "nothing", "mode": "write", "ran_at": 1893916860.0, "row_at": 1893916800.0, "wrote": ["work", "feed"], "wrote_at": 1893913260.0}
apps.json mode 0o600, lists: work_apps, feed_apps

$ limitless-doctor   (the job row)
job apps ingest: live: write mode: ran under an hour ago after a sync: no new apps reply

schedule card:
Schedule "Apps ingest" (after each sync run, at most once; asleep or awake: it sends nothing, so no window holds it): ends at the next sync run; nothing is sent; it reads your work apps or feed apps reply and, in write mode, sets the app lists from it
files in the state dir: apps-ingest.json, apps.json, hermes.db, runs.jsonl
```
