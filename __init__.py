"""hermes-key-doctor: why did my Hermes key stop working?

Registers:
  * ``hermes keydoctor`` CLI command (``--json`` for the desktop page, ``--alert`` for cron);
  * ``/keys`` slash command with the text report.

The desktop page in ``desktop/plugin.js`` runs ``hermes keydoctor --json`` through the
gateway's ``cli.exec`` RPC. Everything is read-only; tokens are never read out.
"""

from __future__ import annotations

from . import commands


def register(ctx) -> None:
    ctx.register_command(
        "keys",
        handler=commands.slash_command,
        description="Which Bot logins are benched or blocked, and the fix (hermes-key-doctor)",
        args_hint="[profile]",
    )
    ctx.register_cli_command(
        name="keydoctor",
        help="Why did my key stop working? Benched, dead or model-blocked logins per Bot, with the fix",
        setup_fn=commands.setup_argparse,
        handler_fn=commands.handle_cli,
    )
