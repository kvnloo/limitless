# Result tier: raw readings from health tools never enter the prompt

Privacy tiers (README, [privacy-tiers.md](privacy-tiers.md)): T0 raw data never enters a prompt, T1 labels
come from code, T2 a cloud model sees T1 labels only. The plugin's own tools already return digit-free T1
labels. A health MCP server or another health tool does not: it returns raw readings straight into the
model's context. `limitless/result_tier.py` closes that gap with the Hermes `transform_tool_result` hook.
It is off by default.

## The host contract it relies on

From the public hermes-agent repo, not guessed:

- `model_tools.py`, `_apply_transform_tool_result_hook`: after `post_tool_call` and before the result enters
  context, Hermes calls every `transform_tool_result` callback as
  `callback(tool_name=..., args=..., result=..., duration_ms=..., status=..., error_type=..., error_message=...,
  task_id=..., session_id=..., tool_call_id=..., turn_id=..., api_request_id=..., conversation_id=...)`.
  The first `str` any plugin returns replaces the result; None leaves it alone; an exception is logged and
  the original result goes on (fail-open). `status` is `error` when the result is a JSON object with an
  `error`, or the host's failure detector flags it.
- `tools/mcp_tool_schema.py`, `mcp_prefixed_tool_name`: an MCP tool is registered as
  `mcp__<server>__<tool>`, each part with every character outside `[A-Za-z0-9_]` turned into `_` (a server
  named `synthetic-health` becomes `synthetic_health`), clamped to 64 characters with a hash suffix when it
  is longer. So `mcp__<server>__*` covers every tool of one server.
- `hermes_cli/plugins.py`, `VALID_HOOKS`: the hook names the host knows. The published ctx API has no list
  of hook names, so `result_tier.register` reads `VALID_HOOKS` from the host's already-loaded
  `hermes_cli.plugins` module (sys.modules only, never an import) and skips the hook only when that module is
  loaded and lacks the name (an older host gets one content-free log line instead). With no host module loaded
  (a test ctx, or the isolated capability probe of `hermes plugins validate`) the hook registers, since the
  `requires_hermes` floor already guarantees it wherever Hermes loads the plugin. Every tool and the other
  hooks load either way.

## Config

| Key | Default | Meaning |
| --- | --- | --- |
| `t0_tools` | empty (off) | fnmatch globs over tool names, case-sensitive, such as `mcp__<server>__*` or a tool's exact name; one string counts as a list of one |
| `raw_numbers_opt_in` | false | true (JSON true only) leaves every result alone: the person opted in to raw numbers |

## What it replaces

For a tool a glob matches, every number in the result becomes the words `a number`:

- readings with or without a unit: `61 bpm`, `47.5ms` (the unit stays as its own word: `a number ms`),
  `-0.3`, `88%`, `117/74`;
- ISO timestamps and dates, and clock times, each as one number; uuids, ids that are numbers and hex ids
  that start with a digit.

Keys, field names and words stay, even with a digit inside (`spo2`, `hr_7d`): a digit right after a letter,
an underscore or a dot belongs to a word. A JSON result stays valid JSON with the same keys in the same
order: a number value becomes the string `"a number"`, a string value is scrubbed as text, and true, false
and null stay. An alphanumeric id that starts with a letter (`u12ab`) is a word and stays.

It returns None (the result is left alone) for a tool no glob matches, with the opt-in on, for an error
result, for a result that is not a string (bytes, a dict, None), and for a result with no number. Nothing in
it raises: any exception is None, the same fail-open the host applies. A failed audit write never puts the
raw result back.

## Audit

Each replaced result writes one content-free row through `tier_audit` (`tier_audit.result_event`, when the
audit log is on: `LIMITLESS_AUDIT` or config `audit_path`): hook `transform_tool_result:result_tier`, the
glob that matched and the count of numbers replaced. Never a value, the text or a hash of the result. It is
a filter record, not an injection, so `bin/limitless-tier-audit` leaves it out of its counts (as it does the
`message_shape` rows).

## The tool and the doctor row

`limitless_result_tier` is read-only: `value {filter, tool_globs, raw_numbers_opt_in, host_hook}` in words
(`on` or `off`; `no globs`, `one glob`, `two globs` ... `many globs`; `known`, or unknown when the host has
no `transform_tool_result` hook), modality derived, age_h null, and a digit-free T1 label such as
`result filter on: two tool globs`. It never names a glob or a tool. `limitless-doctor` shows
`tool limitless_result_tier: off: no health tools listed (config t0_tools)` while `t0_tools` is empty.

## Example

`python3 -I scripts/result_tier_example.py` runs the real callback and the real tool body on made-up tool
names and made-up readings, in a temporary dir, outside a Hermes host (so `host_hook` says unknown). Its real
output:

```text
# transform_tool_result (config t0_tools: mcp__synthetic_health__*, fake_vitals)
tool: mcp__synthetic_health__get_night (status ok)
before: {"night": {"start": "2033-03-08T23:12:00Z", "resting_hr": 58, "hrv_ms": 41.5, "spo2_pct": 96}, "stages_min": [64, 212, 98], "id": 77120, "note": "woke 2 times"}
after: {"night": {"start": "a number", "resting_hr": "a number", "hrv_ms": "a number", "spo2_pct": "a number"}, "stages_min": ["a number", "a number", "a number"], "id": "a number", "note": "woke a number times"}
tool: fake_vitals (status ok)
before: weight 70.4 kg, systolic/diastolic 117/74, read at 07:45
after: weight a number kg, systolic/diastolic a number/a number, read at a number
tool: mcp__synthetic_health__get_night (status error)
before: upstream timed out after 30 s
after: unchanged (None)
tool: mcp__synthetic_weather__get_today (status ok)
before: high 14 C, rain 40%
after: unchanged (None)

# audit rows (one per replaced result; the glob and the count, never a value)
{"hook": "transform_tool_result:result_tier", "glob": "mcp__synthetic_health__*", "replaced": 9, "tier": "T1", "digits": 0, "sha256": ""}
{"hook": "transform_tool_result:result_tier", "glob": "fake_vitals", "replaced": 4, "tier": "T1", "digits": 0, "sha256": ""}

# limitless_result_tier
{"value": {"filter": "on", "tool_globs": "two globs", "raw_numbers_opt_in": "off", "host_hook": "unknown: this host has no transform_tool_result hook"}, "modality": "derived", "age_h": null, "evidence_tier": "direct", "label": {"label": "result filter on: two tool globs, but this host has no result hook", "tier": "T1", "modality": "derived"}}
"result filter off: no health tools listed"
```
