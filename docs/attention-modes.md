# Attention modes

The person works in a few attention modes. A mode changes only what the person sees: one line at the end of
the state card, which tells the agent how to shape its replies. It never changes what gets done, and it never
sends anything. `limitless/modes.py` keeps the mode in `mode.json` in the state dir; the `/limitless mode`
slash command sets and reads it.

| Mode | Line added to the card |
| --- | --- |
| `brainstorm` | `brainstorm mode: offer options, defer decisions` |
| `pm` | `pm mode: status, blockers, next step` |
| `copilot` | `copilot mode: do the step, report the result` |
| `focused` | `focused mode: answer briefly, hold non-urgent asks` |
| none (no file, or `off`) | nothing: the card as before |

## Setting it

```
/limitless mode            the current mode
/limitless mode focused    set a mode (brainstorm, pm, copilot or focused)
/limitless mode off        back to none
```

Any case, extra spaces ignored. Anything else (`/limitless mode sprint`, `/limitless mode pm now`) gets the
usage line and changes nothing. Replies are digit-free and never show a path. The command uses the host's
slash-command API (`ctx.register_command`, in `hermes_cli/plugins_context.py`). A host without that API
registers every tool and hook as before, with no command. No tool sets the mode, so the model cannot change it
itself.

## What a mode does

- The line goes after the cached card (outside its line cap) and before `tier_audit.gate`, so it is audited
  with the card. Each line is short and has no digits, so a mode never turns a card into a blocked T0 card.
- `focused` also holds every non-urgent ask, the same way a focus block does: the asks plan
  (`tools.asks_view`, the `asks` part of `limitless_window`) gets the window with `hold_asks` set, exactly as
  a Glide focus block gives it. `asks.plan` then holds each ask with its focus-block reason, and `urgent: true`
  still delivers. There is no new gate. Asleep stays asleep (it holds anyway).
- `brainstorm`, `pm` and `copilot` change no plan, no job and no send.
- `mode.json` is `{"mode": "focused"}`, written atomically (a temp file in the state dir, mode 0600, then a
  rename), like `quiet.json`. A missing, unreadable or malformed file, or an unknown mode, reads as none. It
  fails open to the card as before.
- Nothing in `modes.py` sends, runs a process or opens a connection, and a mode never triggers a push.

## Example (synthetic)

The test fixture state dir and asks queue (`tests/fixtures/`), five hours after the fixture wake event (a peak
window). This is real output of `modes.command`, the `pre_llm_call` hook and `limitless_window`'s `asks`:

```
> /limitless mode
mode: none (the card as usual)
[limitless] state card (coarse labels; limitless_state has detail)
window: peak (proxy)
sleep short (proxy); readiness low (imported)
habit this week: Lights down when wind-down starts; today Done
not recording: anki, bike, scale
asks waiting on you
asks: deliver 2, hold 1, fold 1: one decision ready

> /limitless mode focused
mode set: focused mode: answer briefly, hold non-urgent asks
[limitless] state card (coarse labels; limitless_state has detail)
window: peak (proxy)
sleep short (proxy); readiness low (imported)
habit this week: Lights down when wind-down starts; today Done
not recording: anki, bike, scale
asks waiting on you
focused mode: answer briefly, hold non-urgent asks
asks: deliver 0, hold 4, fold 0: decisions waiting

> /limitless mode pm
mode set: pm mode: status, blockers, next step

> /limitless mode sprint
usage: /limitless mode [brainstorm|pm|copilot|focused|off]

> /limitless mode off
mode off: the card as usual
> /limitless mode
mode: none (the card as usual)
```

With `focused` set, the card gains one line and the four asks that were delivered, held or folded all hold,
the same counts a Glide focus block gives (`tests/test_modes_asks.py`).
