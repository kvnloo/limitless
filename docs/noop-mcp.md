# The NOOP agent MCP server, by hand and behind the result filter

A NOOP agent MCP server (stdio) answers health read tools such as `health_snapshot`, `sleep_summary` and
`data_freshness`. The plugin does not rebuild it and never starts it. It only checks the config and says, in the
`limitless-doctor` row, what you still have to do: add the server to the host's `mcp_servers` yourself, after the
result tier filter covers its tools.

## Why the plugin cannot add it for you

Hermes gives a Python plugin no way to register an MCP server. The plugin context has no such method (its
`register_*` methods are listed in hermes-agent `hermes_cli/plugins_context.py`), and the published plugin API
(`hermes_cli/data/plugin_api.json`) names none. Plugin MCP servers exist only for portable packages, which ship
no Python code and declare a static `mcp.json` (hermes-agent `hermes_cli/agent_plugins.py`, `_discover_mcp`;
loaded by `hermes_cli/plugins_loader.py`, `_load_portable_plugin`). This plugin is a native Python plugin, and a
static file could not check `t0_tools` first anyway. So the server is configured by hand, and the plugin
registers nothing for it.

## Config: `noop_mcp`

Off by default: no `noop_mcp`, nothing happens. Set it in the plugin config (`LIMITLESS_CONFIG`, else
`~/.config/limitless/config.json`):

```json
{
  "noop_mcp": {"command": ["<noop-mcp-executable>", "<arg>"], "env": {"<NAME>": "<value>"}, "name": "noop"},
  "t0_tools": ["mcp__noop__*"]
}
```

- `command`: a list of one or more non-empty strings, the executable first.
- `env`: optional, a map of strings to strings.
- `name`: optional, default `noop`: the key you give the server under `mcp_servers` below.

Anything else (a command as one string, an empty list, a number in `env`) reads as `noop_mcp is set but is not a
command list`. Reading the config never starts the command.

## Turn the filter on first

Hermes names each MCP tool `mcp__<name>__<tool>` (every character outside `[A-Za-z0-9_]` becomes `_`), and an
MCP tool's result enters the model's context as it is: raw readings, timestamps, ids. The result tier filter
([result-tier.md](result-tier.md)) turns every number in a listed tool's result into the words `a number`
before it reaches context, but only for tools that config `t0_tools` lists. So `t0_tools` must hold one glob that
covers every tool of the server, `mcp__noop__*` (or `mcp__<name>__*`); a glob for one tool or one family
(`mcp__noop__sleep_*`) is not enough, because the server can add tools. Until it does, the doctor row says
`refused` and you should not add the server. Setting `raw_numbers_opt_in` to true turns the filter off for every
tool; that is your call, and the doctor does not check it.

## Add it to the host by hand

In the host's `config.yaml` (placeholders only: use your own executable, arguments and values):

```yaml
mcp_servers:
  noop:
    command: "<noop-mcp-executable>"
    args: ["<arg>"]
    env:
      <NAME>: "<value>"
```

The key under `mcp_servers` must be the same as `noop_mcp.name` (default `noop`), so the `t0_tools` glob
matches the tool names the host gives it. Then start a new session: the host starts the server itself.

## The doctor row

One row, `NOOP MCP`, right after the tool rows (kind `mcp`; `--strict` never counts it). It reads only the plugin
config: it never starts the server, never reads the host's `config.yaml`, and never prints the command, an env
value or the server name.

| state | row |
|---|---|
| no `noop_mcp` | `NOOP MCP: off: no noop_mcp set` |
| set but malformed | `NOOP MCP: missing: noop_mcp is set but is not a command list` |
| set, `t0_tools` does not cover `mcp__<name>__*` | `NOOP MCP: missing: refused: t0_tools does not cover its tools` |
| set and covered | `NOOP MCP: missing: set but the host cannot register MCP servers; add it to mcp_servers by hand` |

The last row stays `missing` after you add the server: the doctor cannot see the host's `mcp_servers`.
