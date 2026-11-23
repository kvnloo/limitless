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
