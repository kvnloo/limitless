# Focus safe: agents test UI on an agent display, never on the person's screen

The person's phone and desktop are theirs. An agent that taps, types or opens apps on them steals the
person's focus, cursor or keyboard. Agents test phone and desktop UI on a separate agent display (a virtual
display on the phone, an agent X display, an emulator) instead. `limitless/focus_safe.py` notices when a
shell command would drive the person's own screen.

It is advisory. The `pre_tool_call` hook never blocks a call and never rewrites its args: Hermes approvals own
blocking. It is off by default, runs no device commands of its own, kills or restarts nothing and sends
nothing. Fail open: any error inside it is ok, and the call goes on.

## Config

In the limitless config (`LIMITLESS_CONFIG`, else `~/.config/limitless/config.json`):

| Key | Meaning |
|---|---|
| `focus_safe` | `"warn"` turns the hook on; anything else, or no key, is off |
| `focus_safe_serials` | the adb serials of the person's own phones (protected); a list, or one string |
| `focus_safe_agent_displays` | the display ids agents may drive: Android display ids for `input -d` and `am start --display`, X displays (`:99`) for `DISPLAY` |
| `audit_path` | the tier audit log (`docs/privacy-tiers.md`); the hook writes there, off when unset |

With neither `focus_safe_serials` nor `focus_safe_agent_displays` set the guard is inert: every call is `ok`
with the reason "no protected devices set". The serials and display ids come only from config; none are in
the code.

## What it reads

`classify(tool_name, args, serials, agent_displays)` reads only shell-like tools (`terminal`, `shell`, `bash`,
`run_command`, `execute_command`) and their `command` (or `cmd`). The command is split into simple commands
at `;`, `&&`, `|` and parentheses with shell quoting honoured; `NAME=value` prefixes, `export DISPLAY=...` and
wrappers such as `sudo` or `env` are understood, and the words after `adb shell` are split again the way the
phone's shell would. First match in the table wins; a command matching no rule is `ok`.

| Rule | Drives | Ok when | Why (what the agent is told) |
|---|---|---|---|
| `adb-input` | adb shell input tap, swipe, text, keyevent, press or roll on a protected phone | input -d names an agent display, or adb -s names a phone that is not protected | adb input on a protected phone, not on an agent display: it moves the person's screen |
| `adb-am-start` | adb shell am start on a protected phone | am start --display names an agent display, or adb -s names a phone that is not protected | am start on a protected phone, not on an agent display: it opens an app over the person's screen |
| `xdotool` | xdotool key, type, mouse moves, clicks, window activate or focus | DISPLAY names an agent display | xdotool drives the person's desktop, not an agent display |
| `wmctrl` | wmctrl -a, -R or -s (activate a window, switch desktop) | DISPLAY names an agent display | wmctrl moves the person's focus to another window or desktop |
| `osascript` | osascript with activate, keystroke, key code or click | never: the desktop has no agent display | osascript brings an app forward or types into the person's desktop |
| `open-app` | open -a or open -b (bring an app forward) | open -g (the app opens in the background) | open brings an app to the front of the person's desktop |
| `cliclick` | cliclick (any mouse or key event) | never: the desktop has no agent display | cliclick moves the person's mouse or types on their desktop |

Phone rules apply only when `focus_safe_serials` is set. An adb call that names no serial (no `-s`, no
`ANDROID_SERIAL`) may pick a protected phone and is read as one; naming another serial (an emulator) is ok.
Display `0` is the default display and never an agent display. Read-only commands match no rule:
`dumpsys`, `uiautomator dump`, `screencap`, `getprop`, `logcat`, `xdotool getactivewindow` or `search`,
`wmctrl -l`, `osascript` without activate or keystroke, `open` of a file or with `-g` (background).
Every why is plain words, digit-free, and never names a serial or a display id.

## The hook and the Hermes contract

Hermes calls each `pre_tool_call` callback with `tool_name`, `args`, `task_id`, `session_id`, `tool_call_id`,
`turn_id`, `api_request_id`, `middleware_trace` and `conversation_id`, and reads back only three directives:
`block`, `approve` and `modify` (`hermes_cli/plugins.py`, `_get_pre_tool_call_directive_details`; every other
return is ignored). There is no directive that adds a note for the agent, and a callback that raises or times
out blocks the call. So the hook:

- returns None on every call (no block, no approve, no modify);
- on a warn, records the plain note as one content-free line in the tier audit log, hook
  `pre_tool_call:focus_safe`: counts and a hash, never the note, the command, a serial or a display id;
- catches every error itself and is a few string operations, well inside the hook timeout.

The note text is kept (`focus_safe.note`) for a host that lets a hook add one later.

## The tool

`limitless_focus_safe` is read-only: `value {mode, protected_devices, last_warnings_this_week}` in words
("warn" or "off"; "no devices", "one device", "two devices" ... "many devices"; "none this week" ...
"many this week", counted from the audit lines with that hook in the last seven days, and "unknown: the audit
log is off" without an audit path, never none), modality `derived`, `age_h` null, and a digit-free T1 label
such as "focus guard off" or "focus guard warns: one device protected".

## Synthetic example

`python3 -I scripts/focus_safe_example.py`: a made-up config with one protected phone (`SYNTHETIC0001`), an
agent display `7` on it and an agent X display `:99` (both made up), focus_safe warn and a temporary audit log.
It runs the real classify, hook and tool body; no command is run.

```text
# classify (terminal tool)
warn  adb -s SYNTHETIC0001 shell input tap 540 1200
      why: adb input on a protected phone, not on an agent display: it moves the person's screen
ok    adb -s SYNTHETIC0001 shell input -d 7 tap 540 1200
warn  adb -s SYNTHETIC0001 shell am start -n org.example.app/.Main
      why: am start on a protected phone, not on an agent display: it opens an app over the person's screen
ok    adb -s SYNTHETIC0001 shell am start --display 7 -n org.example.app/.Main
ok    adb -s SYNTHETIC0001 shell dumpsys window
ok    adb -s SYNTHETIC0001 exec-out screencap -d 7 -p
ok    adb -s SYNTHETIC0009 shell input keyevent HOME
warn  xdotool key ctrl+l
      why: xdotool drives the person's desktop, not an agent display
ok    DISPLAY=:99 xdotool key ctrl+l
warn  osascript -e 'tell application "Notes" to activate'
      why: osascript brings an app forward or types into the person's desktop
warn  open -a Notes
      why: open brings an app to the front of the person's desktop
ok    open -g -a Notes
# the pre_tool_call hook on every command: what it returns, the audit lines it wrote
returns: None
{"hook": "pre_tool_call:focus_safe", "tier": "T1", "lines": 1, "digits": 0, "blocked": false}
{"hook": "pre_tool_call:focus_safe", "tier": "T1", "lines": 1, "digits": 0, "blocked": false}
{"hook": "pre_tool_call:focus_safe", "tier": "T1", "lines": 1, "digits": 0, "blocked": false}
{"hook": "pre_tool_call:focus_safe", "tier": "T1", "lines": 1, "digits": 0, "blocked": false}
{"hook": "pre_tool_call:focus_safe", "tier": "T1", "lines": 1, "digits": 0, "blocked": false}
# the note an agent would see, if the host let a pre_tool_call hook add one
focus safe: adb input on a protected phone, not on an agent display: it moves the person's screen. Run it on an agent display, or ask the person first.
# limitless_focus_safe
{"value": {"mode": "warn", "protected_devices": "one device", "last_warnings_this_week": "five this week"}, "modality": "derived", "age_h": null, "evidence_tier": "direct", "label": "focus guard warns: one device protected"}
```
