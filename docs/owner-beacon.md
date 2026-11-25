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
  nothing, leaves an old beacon alone, prints one line and exits 0. When the newest time is the one already
  in a valid beacon at `--out`, the file is left unchanged (same bytes, same mtime) and one line says so;
  any other case (no file, not a beacon, an older or newer time) writes it as above.
- **Read** (on the plugin host): list the copies in `LIMITLESS_OWNER_BEACONS` (os.pathsep-separated) or
  config `owner_beacons` (a list; relative paths are in the state dir). The newest of every DB and beacon
  wins. Each beacon counts as one source: failed when missing, unreadable, malformed or stamped more than
  `SKEW_S` (five minutes) in the future. A beacon newer than the catch-up bound is ignored, so this turn's
  own message never counts as last seen.
- **Unknown stays unknown**: with no DB and no beacon configured the gap is unknown and nothing is added.
  A stale beacon is just an old time; it never means away by itself.
- **What counts.** The newest role `user` message from any session source except the ones Hermes starts by
  itself: `cron`, `kanban` and `subagent` prompts are not counted (`AUTOMATED_SOURCES`: their `user` rows are a
  job's prompt, a card's brief or a delegated goal, never you). Every other source is: the CLI, the desktop
  and gui apps, chat platforms, and one-shot runs.
- **Transport is yours.** Nothing here copies or sends, and nothing is installed by the plugin: the script and
  service files below are text for you to adapt. See the operator recipe.

## Operator recipe: a writer on a schedule, copied to the plugin host

On the machine you chat from, one small script writes the beacon and copies it to `<plugin host>`, into
`<state dir>/beacons/` (the plugin host's limitless state dir). Placeholders in angle brackets are yours to fill
in; `this-machine` is any name you like. The copy needs an SSH key that works without a prompt.

```
#!/bin/sh
# ~/bin/owner-beacon-push.sh (yours; the plugin does not install it)
set -e
mkdir -p "$HOME/.cache/limitless"
<limitless checkout>/bin/limitless-owner-beacon write --out "$HOME/.cache/limitless/owner-beacon.json"
rsync -t --chmod=F600 "$HOME/.cache/limitless/owner-beacon.json" "<plugin host>:<state dir>/beacons/this-machine.json"
```

Run it every hour. When nothing new was said, the writer leaves the file unchanged, so its mtime stays put;
`rsync -t` keeps that mtime on the copy, and the next run's size-and-mtime check finds nothing to move. Only a
changed beacon crosses the network. With no message to report the writer exits 0 and writes nothing, so rsync
again finds nothing to move.

macOS, launchd (text only; save as `~/Library/LaunchAgents/<label>.plist`, then
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist`):

```
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string><label></string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string><home>/bin/owner-beacon-push.sh</string></array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
```

Linux, systemd user units (text only; save both under `~/.config/systemd/user/`, then
`systemctl --user enable --now owner-beacon.timer`):

```
# owner-beacon.service
[Unit]
Description=Write the owner beacon and copy it to the plugin host

[Service]
Type=oneshot
ExecStart=/bin/sh %h/bin/owner-beacon-push.sh
```

```
# owner-beacon.timer
[Unit]
Description=Owner beacon, hourly

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h

[Install]
WantedBy=timers.target
```

On the plugin host, in `config.json`: `"owner_beacons": ["beacons/this-machine.json"]` (relative to
`<state dir>`).
