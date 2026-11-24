# Upstream PR text: the cron decision-window gate

This file holds the title and body for one pull request into NousResearch/hermes-agent `main`. It
is text only. The code is on the public fork branch `up/cron-decision-window-gate-r2`
(head `a910662`, the same 6 commits rebased on upstream `fe9a4b5`, no conflicts). The older branch
`up/cron-decision-window-gate` (head `16a9936`, on `0f602c5`) is kept as it was. The PR is opened from
the `-r2` branch, by hand, after review here.

The body follows the upstream `.github/PULL_REQUEST_TEMPLATE.md` sections, plus a "Not in this PR"
list. It covers one concern: holding a due cron job until its decision window is open. Every
example in it is synthetic. Copy the two fenced blocks as they are.

## Title

```text
feat(cron): hold due jobs outside a plugin's decision window
```

## Body

```markdown
## What does this PR do?

A recurring cron job can now say when it should speak, not only when it is due. It adds two
optional job fields and one plugin hook:

- `window_class`: `peak` (asks for a decision), `trough` (a review or an easy read),
  `wind_down` (an end-of-day question) or `anytime`.
- `stale_after_s`: seconds after the due instant past which the occurrence is dropped, because a
  late reminder is noise. It also covers a late catch-up run.
- `ctx.register_window_provider(provider)`: a plugin says which window is open now.
  `provider.current(now)` returns a window class or `None`. One provider per profile.

On each tick, a due job that set either field goes through `cron.decision_window.gate()`:

- window open (or the provider says `anytime`): it fires as usual.
- other or unknown window: it is held. No run is recorded, the due instant does not move, and
  `last_fire_error` says why. `hermes cron list` shows it as a hold, not a gateway outage. A later
  tick fires it once the window opens, within the job's catch-up window.
- older than `stale_after_s`: it is dropped and the job moves to its next slot.
- `hermes cron run`: never held.

Hermes ships no provider and reads no clock for this. Which window is open is the plugin's call.
The core part is two fields, a pure `gate()` and one tick step next to
`cron/scheduler_gateway_gate.py`.

**Users who never register a window provider: nothing changes.** No existing job has these
fields, so the tick returns the due list untouched and never resolves a provider. If a job sets
`window_class` with no provider, the built-in `ALWAYS_ANYTIME` opens every window and the job
fires when due, as before. `stale_after_s` only acts on a job that sets it. The `cronjob` tool
schema, the CLI flags and the prompt surface are unchanged.

## Related Issue

Part of #158538 (STEP 2: a job states when it speaks and when it ends). Design comment:
https://github.com/NousResearch/hermes-agent/issues/158538#issuecomment-7086516039

That comment asked: catalog plugin, or a small core patch with the provider as a plugin hook?
This PR is the core-patch shape. It also asked whether a hold should queue the message. Here it
does not: the due instant stays put and a later tick fires it.

## Type of Change

- [x] ✨ New feature (non-breaking change that adds functionality)

## Changes Made

- `cron/decision_window.py` (new): `WindowClass`, the `WindowProvider` protocol,
  `ALWAYS_ANYTIME`, the field normalizers, `validate_window_knobs()` and the pure `gate()`.
- `cron/scheduler_window_gate.py` (new): `hold_outside_window()`, called from
  `cron/scheduler_tick.py` after the headless gateway gate. It stamps held jobs and advances
  stale ones.
- `cron/jobs.py`, `cron/job_definition.py`: create/update accept and validate the two fields;
  both need a recurring (cron or interval) schedule. A shipped profile keeps them.
- `hermes_cli/plugins_context.py`, `hermes_cli/plugins.py`: `register_window_provider()` and
  `get_plugin_window_provider()`, leased like `register_context_engine` so unload frees the slot.
  A second provider is refused with a warning.
- `hermes_cli/plugin_isolation.py`: the hook is in-process only.
- `hermes_cli/cron.py`: `cron list` words a hold as a decision window, not a gateway outage.
- Docs: `website/docs/user-guide/features/cron.md` (Decision windows),
  `website/docs/user-guide/features/plugins.md`, `website/docs/developer-guide/cron-internals.md`,
  `cron/AGENTS.md`.
- Tests: `tests/cron/test_decision_window.py`, `tests/cron/test_window_gate_tick.py`,
  `tests/hermes_cli/test_plugin_window_provider.py`.

## How to Test

1. The new tests:
   `just test tests/cron/test_decision_window.py tests/cron/test_window_gate_tick.py tests/hermes_cli/test_plugin_window_provider.py`
2. The "nothing changes" claim:
   `scripts/run_tests.sh tests/cron/test_window_gate_tick.py -k fires_as_before`
   and `scripts/run_tests.sh tests/hermes_cli/test_plugin_window_provider.py -k without_a_plugin`.
   The first test fails if a tick with no opted-in job even resolves the provider.
3. The neighbours: `just test tests/cron/test_jobs.py tests/cron/test_scheduler.py tests/hermes_cli/test_cron.py`
4. `just check`
5. By hand, with a synthetic plugin whose `current(now)` returns `"trough"` and a job created
   with `window_class="peak"`: after a tick, `hermes cron list` shows the line under Logs, and
   `hermes cron run <id>` still fires it.

## Checklist

### Code

- [ ] I've read the Contributing Guide
- [x] My commit messages follow Conventional Commits
- [ ] I searched for existing PRs to make sure this isn't a duplicate
- [x] My PR contains **only** changes related to this feature
- [ ] I've run `just test` on the tests for the code I changed, and they pass
- [ ] `just check` passes
- [x] I've added tests for my changes
- [ ] I've tested on my platform:

### Documentation & Housekeeping

- [x] I've updated relevant documentation
- [x] I've updated `cli-config.yaml.example` if I added/changed config keys — N/A (job fields, not config keys)
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md` if I changed architecture or workflows (`cron/AGENTS.md`)
- [x] I've considered cross-platform impact — N/A (no file I/O, process or terminal changes)
- [x] I've updated tool descriptions/schemas if I changed tool behavior — N/A (the `cronjob` tool is unchanged)

## Not in this PR

These stay in the plugin that consumes the hook:

- The provider itself: which events open a window (waking up, a focus block ending).
- The send gate: cross-job dedupe, a daily push cap, folding repeated reminders.
- The evidence envelope for reported values.
- One decision per `peak` window, and `expires` end events.
- Queuing a held message for the next window.
- CLI flags, `cronjob` tool fields and dashboard fields for the two job fields.

## Screenshots / Logs

A held job in `hermes cron list` (synthetic job, synthetic time):

    ⚠ decision window at 2026-01-05T12:00:00+00:00: Held: trough window open: holds the peak job; it fires once the window opens.
```

## Notes for the opener

- Before opening: rebase the fork branch on current upstream `main`, run steps 1 to 4, then tick
  the open checklist boxes. The boxes left open are the ones only a fresh run can tick.
- The test names below are copied from the fork branch. If the branch changes, update this list
  and the constant in `tests/test_upstream_pr_body_docs.py`.

Tests the fork branch adds:

- `tests/cron/test_decision_window.py`: a job without window fields fires and never asks the
  provider; the default provider reports anytime, so every class fires; a matching window fires
  and names it; another window holds with a reason naming both classes; an unknown window holds;
  the provider may answer with the plain string; an anytime job fires even when the provider knows
  nothing; the provider receives the tick instant; a stale occurrence does not fire even in its
  window; a fresh occurrence is not stale; `stale_after_s` alone drops a late catch-up run; a
  manual run is never gated; normalizer accept and reject cases.
- `tests/cron/test_window_gate_tick.py`: an existing job fires as before without consulting a
  provider; create persists the fields; create rejects bad fields; the fields need a recurring
  schedule; update sets and clears them; update checks the window against the new schedule; a
  held job keeps its due instant and says why; a held job fires on the tick its window opens; a
  stale recurring occurrence is dropped and the job moves on; a profile distribution keeps the
  fields; `cron list` explains a hold without blaming the gateway.
- `tests/hermes_cli/test_plugin_window_provider.py`: a plugin registers the provider the tick
  uses; without a plugin every window is open; a second provider is refused; unloading the plugin
  frees the slot; an object without `current` is refused.
