# The app-lists ask in the wake brief

The work-app and feed-app lists (`flow_work_apps`, `feed_apps`) ship empty, so deep work, focus blocks, the
flow ledger and the feed reflex answer unknown until one is set. [app-candidates.md](app-candidates.md)
proposes the lists from observed app time and [apps-ingest.md](apps-ingest.md) reads one reply back. This
puts the proposal where the person can answer it: while both lists are unset, the wake brief ends with two
lines,

```
Reply with this to set your app lists (edit freely):
work apps: termux
feed apps: instagram, reddit
```

The second part is `app_candidates.reply_line` exactly (one line per list that has an app), so the person can
send it back as it is, or edit it first, and `bin/limitless-apps-ingest` sets the lists from it.

## When it is asked

`limitless/apps_ask.py`, `ask_lines(cfg, state_dir, now)`, gives no lines when:

1. config `apps_ask` is off (`false`, `"off"`, `"false"` or `"no"`; the default is on);
2. either list is already set: `apps_reply.lists_for`, so the environment (`LIMITLESS_FLOW_WORK_APPS`,
   `LIMITLESS_FEED_APPS`), the config or `apps.json` from a reply;
3. the ask was told less than seven days ago (`apps-ask.json`); or
4. the candidates are unknown (`app_candidates.read_for`: no ActivityWatch source, too little app time, no
   well-known work or feed app).

The seven days are a duration since the last delivered ask, never a time of day. A missing or malformed
mark counts as never told.

## Said once, told only after a real delivery

The same rule as the input-outage line ([outage.md](outage.md)). `jobs_runner.brief_apps_ask` passes the lines
through the tier audit gate (hook `brief:apps_ask`) and `brief_post.finalize` puts them last in the brief.
`bin/limitless-brief send` sends the brief the way it always has (no new push, no new job); only when that
delivery reached Telegram does it call `jobs_runner.brief_apps_ask_told`, which writes `apps-ask.json`. A
failed delivery writes nothing, so the next brief asks again. `bin/limitless-brief build` previews the lines and
writes nothing.

`apps-ask.json` is `{"told": <epoch seconds>}`, written atomically (a temp file in the state dir, mode 0600,
then a rename). It never holds an app name.

kevin-push holds every message to its shape ([message-shape.md](message-shape.md)). On a long brief it folds the
middle lines, but it keeps this closing ask whole, never folded or cut, so the lines that are marked told are
the lines the person sees.

The gate blocks a line with a digit unless the raw opt-in is set, so a proposal naming an app with a digit in
its name is left out of the brief (and nothing is marked); the person can still run
`bin/limitless-app-candidates`.

## Where the app names go

The app names are the person's own data. They appear only in the brief text sent to the person. Never in the
`pre_llm_call` state card, the catch-up hook, a doctor reason, a tier audit row (counts and a hash only), a T1
label or `apps-ask.json`. `tests/test_apps_ask_privacy.py` pins this.

## Doctor

The `apps ask` row ([doctor.md](doctor.md)), right after the `apps lists` row, in words only:

| Status: reason starts with | When |
| --- | --- |
| `off` | config `apps_ask` is off |
| `live`: `not needed` | a list is set |
| `live`: `told recently` | asked in a delivered brief less than seven days ago |
| `live`: `waiting` | both lists unset; the next brief asks once the candidates are known |

The row reads config, `apps.json` and `apps-ask.json` only, never app time.

Nothing here sends, pushes, writes config or starts anything; the brief's sender never sends a second message.
Stdlib only, Python 3.9+.

## Synthetic run

`python3 -I scripts/apps_ask_example.py`: a made-up week of phone app time (well-known public app ids only)
in a temporary state dir, at fixed times. Its real output:

```text
## both lists unset: the doctor row, then the brief
apps ask: live: waiting: the next wake brief proposes the app lists once app time names a work or feed app
State: synthetic
Reply with this to set your app lists (edit freely):
work apps: termux
feed apps: instagram, reddit
## apps-ask.json before any delivery: absent
## the brief went out (a real delivery): the sender marks it told
apps-ask.json (mode 600) keys: ['told']
apps ask: live: told recently: asked in a delivered brief this week; asked again after a week if both lists stay unset
## five days later
State: synthetic
## eight days later, still unset (a fresh week of app time)
apps ask: live: waiting: the next wake brief proposes the app lists once app time names a work or feed app
State: synthetic
Reply with this to set your app lists (edit freely):
work apps: termux
feed apps: instagram, reddit
## the person replied: a list is set
apps ask: live: not needed: an app list is set
State: synthetic
## config apps_ask off
apps ask: off: the wake brief never asks for the app lists (config apps_ask)
## the tier audit rows: counts and a hash, never a name
hook=brief:apps_ask lines=3 digits=0 blocked=False
hook=brief:apps_ask lines=3 digits=0 blocked=False
```
