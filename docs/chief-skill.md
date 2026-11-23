# The chief skill, limitless:chief

The plugin's third read-only Hermes skill, [skills/chief/SKILL.md](../skills/chief/SKILL.md), is what an agent
follows when it wants something from the person. It wraps the asks queue and the decision window that
already exist ([decision-window.md](decision-window.md#asks), `limitless/asks.py`); it adds no tool, no job
and no store.

- Ask: the agent appends one ask to the asks queue (the JSONL at `LIMITLESS_ASKS` or config `asks_path`)
  instead of messaging the person, with only the fields `asks.py` reads: `id`, `kind`
  (decision | approval | fyi), `effort` (deep | light), `title`, `at`, `urgent` and optional `answers`.
  It never sets `delivered_at`; the host does, once the ask reached him.
- One tap: the title is one line in plain words, never a card id or a typed-answer prompt; the reply is
  Yes / No / Later (or two to four one-word choices). Later is never a no.
- Window: the agent calls `limitless_window` and lets the plan decide. Decisions only in a peak window, at
  most one per peak window; FYIs fold into the next brief line in a trough; a focus block (or focused mode)
  holds everything unless urgent; asleep holds until wake. Urgent is for what cannot wait for the next peak.
- Status board: one board in words (what landed, what waits on him, what is blocked), edited in place and
  rebuilt from the asks queue, `limitless_flow_ledger` and `limitless_overnight`; never a second store.
- Commit: suggest and prepare; commit only after his confirmation in his one-tap reply.

Event cues only, never a clock time; no advice on what to take; no score.

## Registration

`limitless/coach_skill.py` holds `NAMES = ("coach", "learn", "chief")`; each name's text is
`skills/<name>/SKILL.md`. `register(ctx)` calls `coach_skill.register(ctx)` after the tools, hooks and
schedule cards:

- A host whose ctx has a callable `register_skill` (Hermes: `register_skill(name, path, description="",
  frontmatter=None)`) gets one call per name, in order, each with the description from that skill's own
  frontmatter. The agent loads this one as `limitless:chief` with `skill_view`.
- A host without it (an older Hermes) gets nothing and one content-free info line in all:
  `limitless: the host has no skill registration; the plugin's skills are not registered`
- A call that raises (a bad name, a missing file, anything else) gets one content-free warning line and
  the next skill is still offered, so any one refused skill never stops the other two:
  `limitless: the host's skill registration failed; register went on`

The tests: `tests/test_chief_skill.py` keeps the skill under the shared size cap
(`skill_checks.SKILL_MAX_LINES`, the tighter of the coach and learn caps), its frontmatter name `chief`
with a "Use when ..." description, every tool it names in `plugin.yaml` `provides_tools`, no clock time,
no dosing word and no digit outside its one fenced example (`skill_checks.digits_outside_fences`). The
fenced example is parsed and run through `asks.classify`, `asks.render` and `asks.plan`, so it stays a row
the plugin really reads: a peak decision, one tap, delivered at peak, held after the window's one decision,
in a trough and in a focus block. `tests/test_chief_register.py` registers against fake hosts with, without
and partly refusing `register_skill`.

## Registration test output

```text
$ python3 -I -m unittest discover -s tests -p test_chief_register.py -v
test_a_host_with_register_skill_gets_all_three_in_order (test_chief_register.Register.test_a_host_with_register_skill_gets_all_three_in_order) ... ok
test_a_host_without_it_gets_one_line_for_all_three (test_chief_register.Register.test_a_host_without_it_gets_one_line_for_all_three) ... ok
test_a_missing_chief_file_still_lets_coach_and_learn_register (test_chief_register.Register.test_a_missing_chief_file_still_lets_coach_and_learn_register) ... ok
test_any_one_refused_call_still_lets_the_other_two_register (test_chief_register.Register.test_any_one_refused_call_still_lets_the_other_two_register) ... ok
test_the_names_are_coach_learn_chief_with_a_file_each (test_chief_register.Register.test_the_names_are_coach_learn_chief_with_a_file_each) ... ok

----------------------------------------------------------------------
Ran 5 tests in 0.115s

OK
```

## Against a real Hermes host

The checkout loaded as a directory plugin (`plugins.enabled: [limitless]`) into a Hermes install's own
`PluginManager`, in a throwaway Hermes home:

```text
list_plugin_skills('limitless'): ['chief', 'coach', 'learn']
find_plugin_skill('limitless:chief') -> skills/chief/SKILL.md
find_plugin_skill('limitless:coach') -> skills/coach/SKILL.md
find_plugin_skill('limitless:learn') -> skills/learn/SKILL.md
metadata: {'name': 'limitless:chief', 'description': 'Use when an agent needs something from the person. Queue one ask, let the window decide.'}
```
