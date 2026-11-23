# The coach skill, limitless:coach

The plugin ships one read-only Hermes skill, [skills/coach/SKILL.md](../skills/coach/SKILL.md). It tells an
agent which limitless tool answers which question and the rules for using them: explain, suggest with the
tool's evidence tier, prepare, and commit only after the person says yes. It is never an order-giver: no
advice on what to take, no diagnosis, no capability score, no clock times, and nudges only through the
plugin's own jobs and send gate. The skill adds no tool, no job and no write.

## Registration

`register(ctx)` calls `coach_skill.register(ctx)` last, after the tools, hooks and schedule cards
(`limitless/coach_skill.py`):

- A host whose ctx has a callable `register_skill` (Hermes: `register_skill(name, path, description="",
  frontmatter=None)`) gets one call per name in `coach_skill.NAMES` (`coach`, then `learn`, see
  [learn-skill.md](learn-skill.md)), `register_skill("coach", <plugin dir>/skills/coach/SKILL.md,
  description=<the skill's frontmatter description>)`. The agent then loads it as `limitless:coach` with
  `skill_view`, and `skills_list` shows it while the plugin is enabled.
- A host without it (an older Hermes) gets nothing and one content-free info line in all:
  `limitless: the host has no skill registration; the plugin's skills are not registered`
- A call that raises (a bad name, a missing file, anything else) gets one content-free warning line, the
  next skill is still offered, and every other registration has already happened:
  `limitless: the host's skill registration failed; register went on`

Both lines come from the `limitless.coach_skill` logger, so the schedule-card line from `limitless.plugin`
stays the only one there.

The tests: `tests/test_coach_skill.py` keeps the skill short, its frontmatter name `coach`, every tool it
names in `plugin.yaml` `provides_tools`, its question-to-tool table covering all of them, and no clock time
or dosing word in it. `tests/test_coach_register.py` registers against fake hosts with, without and raising
`register_skill`.

## Registration test output

```text
$ python3 -I -m unittest discover -s tests -p test_coach_register.py -v
test_a_host_with_register_skill_gets_the_coach_skill (test_coach_register.Register.test_a_host_with_register_skill_gets_the_coach_skill) ... ok
test_a_host_without_it_gets_one_content_free_line_and_nothing_else (test_coach_register.Register.test_a_host_without_it_gets_one_content_free_line_and_nothing_else) ... ok
test_a_missing_skill_file_reaches_the_host_and_is_caught (test_coach_register.Register.test_a_missing_skill_file_reaches_the_host_and_is_caught) ... ok
test_a_non_callable_attribute_is_no_host (test_coach_register.Register.test_a_non_callable_attribute_is_no_host) ... ok
test_a_raising_host_never_breaks_the_other_registrations (test_coach_register.Register.test_a_raising_host_never_breaks_the_other_registrations) ... ok
test_the_description_is_the_frontmatter_one (test_coach_register.Register.test_the_description_is_the_frontmatter_one) ... ok
test_the_names_are_the_documented_ones (test_coach_register.Register.test_the_names_are_the_documented_ones) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.076s

OK
```

## Against a real Hermes host

The checkout loaded as a directory plugin (`plugins.enabled: [limitless]`) into a Hermes install's own
`PluginManager`, which has `register_skill`:

```text
list_plugin_skills('limitless'): ['coach', 'learn']
find_plugin_skill('limitless:coach') -> skills/coach/SKILL.md
metadata: {'name': 'limitless:coach', 'description': 'Use when coaching over limitless tools. Act only on a yes.'}
```
