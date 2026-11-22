"""Plugin wiring: tool schemas -> handlers, hooks. Uses only the published ctx API:
ctx.register_tool(name, toolset, schema, handler, ..., description, emoji) and ctx.register_hook(name, fn).
"""
from __future__ import annotations

TOOLSET = "limitless"
TOOLS: dict = {}   # name -> (schema, handler, emoji)
HOOKS: dict = {}   # hook name -> callback


def register(ctx) -> None:
    for name, (schema, handler, emoji) in TOOLS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler,
                          description=schema["description"], emoji=emoji)
    for hook, fn in HOOKS.items():
        ctx.register_hook(hook, fn)
