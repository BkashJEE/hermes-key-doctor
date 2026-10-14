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
    k.mark_shared(results)
    counts = {s: 0 for s in k.STATES}
    for r in results:
        for c in r.get("credentials", []):
            c["state"] = k.state_of(c)
            c["note"] = k.note_for(c, now)
            counts[c["state"]] += 1
            c["why"] = k.why(c) if c["status"] == "benched" else None
            c["fix"] = k.fix_for(r["profile"], c)
            c["until_text"] = k.when(c["benched_until"], now) if c["benched_until"] else None
            c["cooldowns"] = [{"model": m, "until": t, "until_text": k.when(t, now), "stuck": t - now > 7 * 86400} for m, t in c["model_cooldowns"].items()]
        dm = r.get("default_model")
        if dm:
            dm["line"] = k.model_line(r["profile"], dm)
            dm["stopped"] = dm.get("reach", {}).get("verdict") == "blocked" and not dm.get("covered")
    total = sum(counts.values())
    bots_stopped = sum(1 for r in results if (r.get("default_model") or {}).get("stopped"))
    crons_failing = sum(len(k.blocked_crons(r)) for r in results)
    return {"checked_at": now, "profiles": results, "risks": k.single_points(results),
            "summary": {"logins": total, "bots": len(results), **counts, "bots_stopped": bots_stopped, "crons_failing": crons_failing,
                        "crons": sum(len(r.get("crons", [])) for r in results), "attention": total - counts["ok"] + bots_stopped + crons_failing}}


def text_report(profile: str | None = None) -> str:
    k = _doctor()
    results = [k.read_profile(n, h) for n, h in k.profiles() if not profile or n == profile]
    k.mark_shared(results)
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
            results = [k.read_profile(n, h) for n, h in k.profiles() if not only or n == only]
            k.mark_shared(results)
            text = k.alert(results, time.time())
            if text:
                print(text)
        else:
            print(text_report(only))
    except Exception as e:  # the page shows this instead of crashing
        if getattr(args, "json", False):
            sys.stdout.write(json.dumps({"error": f"key doctor failed: {type(e).__name__}: {e}"}) + "\n")
        else:
            print(f"key doctor failed: {e}")
