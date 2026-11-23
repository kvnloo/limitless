# App candidates: the work-app and feed-app lists, proposed as one reply

Six features stay unknown until config `flow_work_apps` (work apps) and `feed_apps` (feed apps) exist: the
flow week, focus blocks, the break nudge, flow metrics, the feed reflex and the desktop ActivityWatch rows
that feed them. Typing two lists is an ask that does not get done. `limitless/app_candidates.py` fills the
lists in from the person's own app time, so the ask becomes one reply to confirm:

```
work apps: code, alacritty
feed apps: instagram, tiktok, reddit
```

## The rule

- **Rows.** The last `LOOKBACK_DAYS` (seven) days of app-in-foreground rows, from the phone's ActivityWatch DB
  (config `aw_db`, read by `blocks.read_rows`, cut to not-afk time) and the desktop's (`aw_desktop`: config
  `desktop_aw_url` or `desktop_aw_export`). Either source is enough; a source that is set and cannot be read
  is left out while the other is used.
- **Per app.** Foreground time is summed per app. Names are trimmed and case-folded; the names one row
  carries together (a display name and its Android package id) are one app, and so are the aliases of one
  `KNOWN` app. An app is named by the name that covers the most of its time (the display name on a tie),
  so the name matches the rows once it is in config. A name with a comma, a line break or the `title:`
  prefix would not survive the reply and is left out.
- **Split.** `KNOWN` is a small built-in, public map of well-known app ids and names. Feeds: Instagram,
  TikTok, X or Twitter, Reddit, YouTube, Facebook, Snapchat, Threads and their Android package ids. Work:
  code editors (Code, Cursor, Zed, Sublime Text, JetBrains IDEs, Emacs, Vim), terminals and GitHub.
  Browsers are never work by default: work or feed depends on the tab, so a browser is `other`, as is
  every app the map does not know.
- **Kept.** Apps already in `flow_work_apps` or `feed_apps` (config or `$LIMITLESS_FLOW_WORK_APPS` /
  `$LIMITLESS_FEED_APPS`) are marked kept and are never dropped: they stay in their own list with the
  person's own spelling, even when not seen this week. The config beats the map.
- **Top N.** Each list then takes up to `MAX_N` (five) new apps by time; config `app_candidates_max` (a
  whole number of at least one) changes it. `other` holds the top apps the map does not place, for the
  raw view only.
- **Unknown, never empty lists.** No source set (`unknown: no ActivityWatch source set (aw_db, desktop_aw_url or desktop_aw_export)`),
  no readable source (its own reason), no rows (`unknown: no app activity rows`), less than `MIN_TOTAL_S`
  (thirty minutes) of app time (`unknown: too little app activity to propose lists`), or no work or feed
  app at all (`unknown: no well-known work or feed app seen`).

`reply_line(c)` is the exact text the person can send back: `work apps: A, B` and `feed apps: C, D`, one
line per list that has an app (two lines at most), empty when unknown. It is the same
`work apps: ...` / `feed apps: ...` shape the person was asked to type.

## Words, and where app names may appear

The T1 label is digit-free words only: "work and feed app lists proposed", "work app list proposed",
"feed app list proposed" or "unknown: <why>". App names are the person's own data. They appear only in
the reply text (`reply_line`, the CLI's output) and in the tool's value under the raw opt-in
(`LIMITLESS_RAW_IN_PROMPT`); never in the label, the state card, a doctor reason or a log.

- Tool `limitless_app_candidates`: an envelope (modality proxy: an app in the foreground is not work or a
  feed read; aged by the newest row) whose value is `{label, work, feed}` in words such as "three apps, one
  kept". With the raw opt-in the value adds `reply`, the `work`, `feed` and `other` lists (name, seconds,
  kept), `sources`, `total_s` and `max_n`. Unknown is value null with the reason.
- CLI `bin/limitless-app-candidates`: prints the reply lines for the person (their own terminal or a push
  they choose to send); `--json` prints the label, the reply and the lists. Unknown prints no reply, the
  plain reason on stderr, and exits 0.
- The doctor lists the tool like every other (`tool limitless_app_candidates`): live, or off / missing with
  the plain reason, never the lists.

It only suggests: it never writes config or any file and never sends. The person replies, and only that
reply sets the lists. Durations only, never a clock time; no score, no ranking of the person, no target.

## A synthetic run

`python3 -I scripts/app_candidates_example.py` builds a made-up week (a phone DB and a desktop export in a
temporary dir; well-known public app ids and made-up app names only) and prints:

```text
## reply_line
work apps: code, alacritty
feed apps: instagram, tiktok, reddit
## reply_line, feed_apps already set to Snapchat, app_candidates_max two
work apps: code, alacritty
feed apps: instagram, tiktok, Snapchat
## limitless_app_candidates (no raw opt-in)
{"age_h": 2.7, "evidence_tier": "indirect", "label": {"label": "work and feed app lists proposed", "modality": "proxy", "tier": "T1"}, "modality": "proxy", "value": {"feed": "three apps", "label": "work and feed app lists proposed", "work": "two apps"}}
## limitless_app_candidates value (raw opt-in)
{"feed": [{"kept": false, "name": "instagram", "seconds": 7500.0}, {"kept": false, "name": "tiktok", "seconds": 2400.0}, {"kept": false, "name": "reddit", "seconds": 1500.0}], "label": "work and feed app lists proposed", "max_n": 5, "other": [{"kept": false, "name": "firefox", "seconds": 9000.0}, {"kept": false, "name": "notely", "seconds": 1800.0}], "reply": "work apps: code, alacritty\nfeed apps: instagram, tiktok, reddit", "sources": ["phone", "desktop"], "total_s": 48600.0, "work": [{"kept": false, "name": "code", "seconds": 22800.0}, {"kept": false, "name": "alacritty", "seconds": 3600.0}]}
## limitless_app_candidates, no ActivityWatch source
{"age_h": null, "evidence_tier": "none", "label": {"label": "unknown: no ActivityWatch source set (aw_db, desktop_aw_url or desktop_aw_export)", "modality": "proxy", "tier": "T1"}, "modality": "proxy", "reason": "app candidates unknown: no ActivityWatch source set (aw_db, desktop_aw_url or desktop_aw_export)", "value": null}
## doctor rows
tool limitless_app_candidates: live: answers from a proxy
tool limitless_app_candidates: off: app candidates unknown: no ActivityWatch source set (aw_db, desktop_aw_url or desktop_aw_export)
## bin/limitless-app-candidates
work apps: code, alacritty
feed apps: instagram, tiktok, reddit
## bin/limitless-app-candidates, no source (stderr)
limitless-app-candidates: unknown: no ActivityWatch source set (aw_db, desktop_aw_url or desktop_aw_export)
```
