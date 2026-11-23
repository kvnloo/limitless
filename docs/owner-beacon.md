# Owner beacon: last seen across machines

`limitless_state`, the card and the catch-up ask when you last wrote to any agent. They read the owner
session DBs (`owner_dbs`) on the plugin host. If you mostly chat on another machine whose store the plugin
host cannot open, you look away for days and the catch-up fires when it should not. A beacon fixes that:
the other machine writes a tiny file with only its newest user-message time, and the plugin host reads it
as one more source.

- **Write** (on the other machine): `bin/limitless-owner-beacon write --out PATH [--dbs a.db:b.db]`. It
  reads the DBs (`--dbs`, else `LIMITLESS_OWNER_DBS` or config `owner_dbs`) read-only, with the same query
  as `limitless/owner_messages.py`, and writes `{"at": "<ISO UTC>", "v": 1}` through a temp file and a
  rename, mode 0600. No content, counts, sessions or source names. With no message to report it writes
  nothing, leaves an old beacon alone, prints one line and exits 0.
- **Read** (on the plugin host): list the copies in `LIMITLESS_OWNER_BEACONS` (os.pathsep-separated) or
  config `owner_beacons` (a list; relative paths are in the state dir). The newest of every DB and beacon
  wins. Each beacon counts as one source: failed when missing, unreadable, malformed or stamped more than
  `SKEW_S` (five minutes) in the future. A beacon newer than the catch-up bound is ignored, so this turn's
  own message never counts as last seen.
- **Unknown stays unknown**: with no DB and no beacon configured the gap is unknown and nothing is added.
  A stale beacon is just an old time; it never means away by itself.
- **Transport is yours.** Nothing here copies or sends. One generic example, with placeholder names, on the
  other machine (crontab, every ten minutes):

```
*/10 * * * * limitless-owner-beacon write --out ~/.cache/owner-beacon.json && scp -q ~/.cache/owner-beacon.json plugin-host:.local/state/limitless/beacons/other-machine.json
```

  and on the plugin host, in `config.json`: `"owner_beacons": ["beacons/other-machine.json"]`.
