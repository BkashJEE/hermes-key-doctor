#!/usr/bin/env python3
"""Key Doctor: why did my Hermes key stop working?

After a 429, a 402 or an entitlement error, Hermes benches the credential that failed. The
bench lives in auth.json (``last_status``, the error code and reason, per-model cooldowns), and
``hermes auth list`` / ``hermes auth status`` do not show it: a benched key still reads
"logged in". This prints, for every profile and every pooled credential, whether it is benched,
why, until when, and the exact command that clears it.

It reads through Hermes's own credential code, so "benched until" is what Hermes itself will
honour, not a guess. It is read-only and never prints a token. Run it with Hermes's Python:

    ~/.hermes/hermes-agent/venv/bin/python key_doctor.py            # every profile
    ~/.hermes/hermes-agent/venv/bin/python key_doctor.py -p ceo     # one profile
    ... --json                                                      # machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("HERMES_ROOT", Path.home() / ".hermes"))
AGENT = ROOT / "hermes-agent"


def profiles() -> list[tuple[str, Path]]:
    found = [("default", ROOT)]
    base = ROOT / "profiles"
    if base.is_dir():
        found += [(p.name, p) for p in sorted(base.iterdir()) if p.is_dir() and (p / "config.yaml").exists()]
    return found


def when(epoch: float | None, now: float) -> str | None:
    if not epoch:
        return None
    left = epoch - now
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))
    if left <= 0:
        return f"{stamp} (passed)"
    hours, rest = divmod(int(left), 3600)
    return f"{stamp} (in {hours}h {rest // 60}m)" if hours else f"{stamp} (in {rest // 60}m)"


def inspect_one() -> dict:
    """Runs inside a child process whose HERMES_HOME is the profile being read."""
    sys.path.insert(0, str(AGENT))
    from hermes_cli.auth import read_credential_pool  # noqa: E402
    from agent import credential_pool as cp  # noqa: E402
    from agent.credential_pool_model_cooldowns import model_cooldown_until  # noqa: E402

    now = time.time()
    pools = read_credential_pool() or {}
    out = []
    for provider, raw_entries in sorted(pools.items()):
        entries = [cp.PooledCredential.from_dict(provider, raw) for raw in (raw_entries or []) if isinstance(raw, dict)]
        live = [e for e in entries if e.last_status != cp.STATUS_DEAD]
        for e in entries:
            until = cp._exhausted_until(e, sole_credential=len(live) == 1)
            benched = e.last_status == cp.STATUS_EXHAUSTED and bool(until and until > now)
            cooled = {m: t for m in (e.model_cooldowns or {}) if (t := model_cooldown_until(e, m)) and t > now}
            out.append({
                "provider": provider, "id": e.id, "label": e.label, "auth_type": e.auth_type, "source": e.source,
                "status": "dead" if e.last_status == cp.STATUS_DEAD else "benched" if benched else "ok" if not cooled else "model-cooldown",
                "last_status": e.last_status, "error_code": e.last_error_code, "error_reason": e.last_error_reason,
                "failure_reason": (e.extra or {}).get("failure_reason") or getattr(e, "failure_reason", None),
                "error_message": (e.last_error_message or "")[:200] or None,
                "benched_until": until if benched else None,
                "stale_bench": e.last_status == cp.STATUS_EXHAUSTED and not benched,
                "model_cooldowns": cooled, "sole_credential": len(live) == 1,
            })
    return {"credentials": out}


def read_profile(name: str, home: Path) -> dict:
    env = {**os.environ, "HERMES_HOME": str(home)}
    python = AGENT / "venv" / "bin" / "python"
    run = subprocess.run([str(python if python.exists() else sys.executable), __file__, "--one"], env=env, capture_output=True, text=True, timeout=60)
    if run.returncode != 0:
        return {"profile": name, "error": (run.stderr.strip().splitlines() or ["unreadable"])[-1]}
    return {"profile": name, **json.loads(run.stdout)}


def fix_for(profile: str, c: dict) -> str | None:
    flag = "" if profile == "default" else f"-p {profile} "
    if c["model_cooldowns"] and c["status"] != "benched":
        return f"hermes {flag}auth reset {c['provider']} {c['id']}   # clears the model cooldowns on this credential"
    if c["status"] == "benched" or c["stale_bench"]:
        if c["auth_type"] == "oauth":
            return f"hermes {flag}auth refresh {c['provider']} {c['id']}   # or: hermes {flag}auth reset {c['provider']} {c['id']}"
        return f"hermes {flag}auth reset {c['provider']} {c['id']}"
    if c["status"] == "dead":
        return f"hermes {flag}auth remove {c['provider']} {c['id']}   # then add it again"
    return None


def why(c: dict) -> str:
    code, reason = c["error_code"], c["failure_reason"] or c["error_reason"]
    if code == 402 or reason in ("billing", "billing_unverified"):
        return "billing: the provider says this account cannot pay" + (" (unverified, may be healthy)" if reason == "billing_unverified" else "")
    if code == 429:
        return "rate limited (429)"
    if code == 401:
        return "rejected as unauthorised (401): token expired or revoked"
    if code == 403:
        return "forbidden (403): often a model this account is not entitled to"
    return f"error {code}" if code else (reason or "unknown")


def report(results: list[dict], now: float) -> int:
    trouble = 0
    for r in results:
        if "error" in r:
            print(f"\n{r['profile']}: could not read ({r['error']})"); continue
        creds = r["credentials"]
        bad = [c for c in creds if c["status"] != "ok" or c["stale_bench"]]
        print(f"\n{r['profile']}: {len(creds)} credential(s), {len(bad)} need attention")
        for c in creds:
            mark = {"ok": "ok ", "benched": "BENCHED", "dead": "DEAD", "model-cooldown": "MODEL COOLDOWN"}[c["status"]]
            print(f"  {mark:<14} {c['provider']:<16} {c['label'][:28]:<28} {c['auth_type']:<7} id={c['id']}")
            if c["status"] == "benched":
                print(f"                 why: {why(c)}; until {when(c['benched_until'], now)}" + (" — the only credential for this provider" if c["sole_credential"] else ""))
            if c["stale_bench"]:
                print("                 marked exhausted, bench time has passed; Hermes should retry it, a reset makes sure")
            for model, until in c["model_cooldowns"].items():
                print(f"                 {model}: blocked on this credential until {when(until, now)}" + (" — longer than any rate limit; likely the stuck-cooldown bug (NousResearch/hermes-agent#127917)" if until - now > 7 * 86400 else ""))
            if c["status"] != "ok" and c["error_message"]:
                print(f"                 provider said: {c['error_message']}")
            if fix := fix_for(r["profile"], c):
                print(f"                 fix: {fix}")
        trouble += len(bad)
    total = sum(len(r.get("credentials", [])) for r in results)
    print(f"\nChecked {total} credential(s) across {len(results)} profile(s): {trouble} benched, dead or cooling down.")
    return 1 if trouble else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Why did my Hermes key stop working?")
    parser.add_argument("-p", "--profile", help="one profile (default: all)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--one", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.one:
        print(json.dumps(inspect_one())); return 0
    targets = [(n, h) for n, h in profiles() if not args.profile or n == args.profile]
    if not targets:
        print(f"No profile named {args.profile}."); return 2
    results = [read_profile(n, h) for n, h in targets]
    if args.json:
        print(json.dumps(results, indent=2)); return 0
    return report(results, time.time())


if __name__ == "__main__":
    sys.exit(main())
