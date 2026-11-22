"""Hermes directory-plugin entry point (plugin.yaml + register(ctx)).

Hermes imports this file as package ``hermes_plugins.<slug>`` with the repo root as its path, so the
relative import below finds the ``limitless/`` package. All logic lives there and imports without Hermes.
"""
from .limitless.plugin import register  # noqa: F401
