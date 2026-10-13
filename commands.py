"""``hermes keydoctor`` and ``/keys``: thin wrappers over skills/key-doctor/scripts/key_doctor.py.

The script is the single source of truth (it also runs standalone and from cron), so it is
loaded from its file rather than copied here.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import time
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "skills" / "key-doctor" / "scripts" / "key_doctor.py"


def _doctor():
    spec = importlib.util.spec_from_file_location("hermes_key_doctor_script", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect(profile: str | None = None) -> dict:
    """Every profile's logins and a summary, shaped for the desktop page."""
    k = _doctor()
    now = time.time()
    results = [k.read_profile(n, h) for n, h in k.profiles() if not profile or n == profile]
    counts = {"ok": 0, "benched": 0, "dead": 0, "model-cooldown": 0, "stale": 0}
    for r in results:
        for c in r.get("credentials", []):
            counts["stale" if c["stale_bench"] and c["status"] == "ok" else c["status"]] += 1
            c["why"] = k.why(c) if c["status"] == "benched" else None
            c["fix"] = k.fix_for(r["profile"], c)
            c["until_text"] = k.when(c["benched_until"], now) if c["benched_until"] else None
            c["cooldowns"] = [{"model": m, "until": t, "until_text": k.when(t, now), "stuck": t - now > 7 * 86400} for m, t in c["model_cooldowns"].items()]
    total = sum(counts.values())
    return {"checked_at": now, "profiles": results, "summary": {"logins": total, "bots": len(results), **counts, "attention": total - counts["ok"]}}


def text_report(profile: str | None = None) -> str:
    k = _doctor()
    results = [k.read_profile(n, h) for n, h in k.profiles() if not profile or n == profile]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        k.report(results, time.time())
    return out.getvalue().strip()


def slash_command(raw_args: str) -> str:
    profile = (raw_args or "").strip() or None
    return text_report(profile)


def setup_argparse(subparser) -> None:
    subparser.add_argument("-p", "--only", help="one profile (default: every profile)")
    subparser.add_argument("--json", action="store_true", help="one-line JSON for the desktop page")
    subparser.add_argument("--alert", action="store_true", help="only problems; nothing when healthy")
    subparser.set_defaults(func=handle_cli)


def handle_cli(args) -> None:
    only = getattr(args, "only", None)
    try:
        if getattr(args, "json", False):
            sys.stdout.write(json.dumps(collect(only), separators=(",", ":"), default=str) + "\n")
        elif getattr(args, "alert", False):
            k = _doctor()
            text = k.alert([k.read_profile(n, h) for n, h in k.profiles() if not only or n == only], time.time())
            if text:
                print(text)
        else:
            print(text_report(only))
    except Exception as e:  # the page shows this instead of crashing
        if getattr(args, "json", False):
            sys.stdout.write(json.dumps({"error": f"key doctor failed: {type(e).__name__}: {e}"}) + "\n")
        else:
            print(f"key doctor failed: {e}")
