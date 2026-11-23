# The rules section, limitless.rules

The coach skill ([skills/coach/SKILL.md](../skills/coach/SKILL.md)) holds the plugin's full contract, but an
agent only reads it when it opens the skill. The per-turn state card (`pre_llm_call`, `limitless/card.py`)
carries data labels, not rules. So the plugin also offers its standing rules as one short system prompt
section, `limitless.rules`, that every new session in the profile gets, whether or not it ever opens the
skill (`limitless/prompt_rules.py`).

## The section

```text
Limitless plugin rules (they hold in every turn):
- Quote the tools' labels, not raw numbers, unless the person opted in.
- A null value is unknown: unknown is never zero and never a no.
- Explain, suggest and prepare; commit only on the person's yes in this turn.
- One habit a week; a skipped day is unlogged, never a miss.
- Cues are events, never a clock time.
- Nudges go only through the plugin's own jobs and send gate; never schedule one yourself.
- Never advise on drugs, medicines, vitamins or amounts to take; never diagnose; no capability score.
- For coaching, open the limitless:coach skill.
```

It is a constant. It reads no state, no config and no clock, holds no digit (so it is T1 by the tier audit
rule in `limitless/tier_audit.py`), no clock time, no dosing word and no host data, and it is the same bytes
in every session, so it stays prompt-cache friendly. The state card stays the only data path, under the
T1/T2 tier audit. The section adds no tool, no job, no write and no push.

## Registration

`register(ctx)` calls `prompt_rules.register(ctx)` last, after the tools, hooks, schedule cards and the
coach skill:

- Config `prompt_rules` (in `LIMITLESS_CONFIG`, `~/.config/limitless/config.json`) is on by default;
  `false` (or `"off"`) registers nothing and logs one content-free info line:
  `limitless: prompt_rules is off in config; the rules section is not registered`
- A host whose ctx has a callable `register_system_prompt_section` (Hermes:
  `register_system_prompt_section(id, content, *, position="after_memory", max_chars=...)`) gets one call:
  id `limitless.rules`, the constant string as content, position `after_memory` and `max_chars` of
  800 (the section is well under it).
- A host without it (an older Hermes) gets nothing and one content-free info line:
  `limitless: the host has no system prompt sections; the rules section is not registered`
- A host that raises (a duplicate id, a bad id, anything else) gets one content-free warning line, and
  every other registration has already happened:
  `limitless: the host's system prompt section registration failed; register went on`

All three lines come from the `limitless.prompt_rules` logger.

## No drift from the coach skill

`tests/test_prompt_rules.py` maps every rule line of the section to the phrases of its matching rule in
`skills/coach/SKILL.md` and fails when a line is added without a mapping or a phrase is no longer in the
skill. A mutation run (an extra unmapped line; a reworded cue line; a skill copy without "Cues are events")
fails that test each time.

## Test output

```text
$ python3 -I -m unittest discover -s tests -p test_prompt_rules.py -v
test_false_turns_it_off_with_one_content_free_line (test_prompt_rules.Config.test_false_turns_it_off_with_one_content_free_line) ... ok
test_no_config_reads_the_host_config (test_prompt_rules.Config.test_no_config_reads_the_host_config) ... ok
test_on_by_default (test_prompt_rules.Config.test_on_by_default) ... ok
test_it_is_short (test_prompt_rules.Content.test_it_is_short) ... ok
test_it_names_every_rule (test_prompt_rules.Content.test_it_names_every_rule) ... ok
test_no_clock_time_and_no_dosing_word (test_prompt_rules.Content.test_no_clock_time_and_no_dosing_word) ... ok
test_no_digit_so_it_stays_t1 (test_prompt_rules.Content.test_no_digit_so_it_stays_t1) ... ok
test_the_id_is_limitless_rules_and_valid (test_prompt_rules.Content.test_the_id_is_limitless_rules_and_valid) ... ok
test_the_module_reads_no_state_and_no_clock (test_prompt_rules.Content.test_the_module_reads_no_state_and_no_clock) ... ok
test_the_same_bytes_every_call (test_prompt_rules.Content.test_the_same_bytes_every_call) ... ok
test_every_rule_line_has_its_rule_in_the_coach_skill (test_prompt_rules.NoDrift.test_every_rule_line_has_its_rule_in_the_coach_skill) ... ok
test_every_rule_line_is_mapped (test_prompt_rules.NoDrift.test_every_rule_line_is_mapped) ... ok
test_the_coach_skill_it_names_is_the_registered_one (test_prompt_rules.NoDrift.test_the_coach_skill_it_names_is_the_registered_one) ... ok
test_a_duplicate_id_is_caught (test_prompt_rules.Register.test_a_duplicate_id_is_caught) ... ok
test_a_host_with_the_method_gets_one_section (test_prompt_rules.Register.test_a_host_with_the_method_gets_one_section) ... ok
test_a_host_without_it_gets_one_content_free_line (test_prompt_rules.Register.test_a_host_without_it_gets_one_content_free_line) ... ok
test_a_raising_host_never_breaks_the_other_registrations (test_prompt_rules.Register.test_a_raising_host_never_breaks_the_other_registrations) ... ok
test_config_false_registers_nothing_through_the_plugin (test_prompt_rules.Register.test_config_false_registers_nothing_through_the_plugin) ... ok
test_the_names_are_the_documented_ones (test_prompt_rules.Register.test_the_names_are_the_documented_ones) ... ok
test_two_sessions_get_the_same_bytes (test_prompt_rules.Register.test_two_sessions_get_the_same_bytes) ... ok

----------------------------------------------------------------------
Ran 20 tests in 0.122s

OK
```
