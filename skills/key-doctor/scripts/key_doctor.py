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


EXPIRY_WARN_S = 24 * 3600  # A5: warn this long before an OAuth login with no refresh token runs out


def epoch_of(value) -> float | None:
    """expires_at may be an ISO string, epoch seconds or epoch ms; None when unknown."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value) / (1000.0 if value > 1e12 else 1.0)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        try:
            v = float(value)
            return v / (1000.0 if v > 1e12 else 1.0)
        except ValueError:
            return None


def anthropic_family(token: str) -> str | None:
    """Which kind of Anthropic secret this is, from its prefix alone (the token is never kept or printed)."""
    t = (token or "").strip()
    if not t:
        return None
    if t.startswith("sk-ant-api"):
        return "console key (sk-ant-api)"
    for pre in ("sk-ant-usr-", "sk-ant-svc-", "sk-ant-admin"):
        if t.startswith(pre):
            return f"console key ({pre.rstrip('-')})"
    if t.startswith("sk-ant-oat"):
        return "subscription OAuth (sk-ant-oat)"
    if t.startswith("eyJ"):
        return "OAuth token (JWT)"
    if t.startswith("cc-"):
        return "Claude Code token (cc-)"
    if t.startswith("sk-ant-"):
        return "anthropic key (other sk-ant-)"
    return "unrecognised format"


def env_names(home: Path) -> set[str]:
    """Names of non-empty variables in a profile's .env. Values are never read past the '='."""
    names = set()
    try:
        for line in (home / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.replace("export ", "").strip()
            if v.strip().strip('"').strip("'"):
                names.add(k)
    except OSError:
        pass
    return names


def inspect_one() -> dict:
    """Runs inside a child process whose HERMES_HOME is the profile being read."""
    sys.path.insert(0, str(AGENT))
    from hermes_cli.auth import read_credential_pool  # noqa: E402
    from agent import credential_pool as cp  # noqa: E402
    from agent.credential_pool_model_cooldowns import model_cooldown_until  # noqa: E402

    now = time.time()
    pools = read_credential_pool() or {}
    out = []
    by_pool: dict[str, list] = {}
    for provider, raw_entries in sorted(pools.items()):
        entries = [cp.PooledCredential.from_dict(provider, raw) for raw in (raw_entries or []) if isinstance(raw, dict)]
        live = [e for e in entries if e.last_status != cp.STATUS_DEAD]
        for e in entries:
            until = cp._exhausted_until(e, sole_credential=len(live) == 1)
            benched = e.last_status == cp.STATUS_EXHAUSTED and bool(until and until > now)
            cooled = {m: t for m in (e.model_cooldowns or {}) if (t := model_cooldown_until(e, m)) and t > now}
            # A5: an OAuth login with no refresh token cannot renew itself; warn before it runs out.
            exp = epoch_of(e.expires_at) or epoch_of(e.expires_at_ms)
            renewable = bool((e.refresh_token or "").strip())
            expiry = None
            if e.auth_type == cp.AUTH_TYPE_OAUTH and exp:
                state = "expired" if exp <= now else "expiring" if exp - now <= EXPIRY_WARN_S else "ok"
                expiry = {"expires_at": exp, "renewable": renewable, "state": state if not renewable else "renews"}
            # B1: what Hermes itself will send an Anthropic secret as (its own classifier), vs. what it is.
            auth_mode = None
            if provider == "anthropic" and (e.access_token or "").strip():
                fam = anthropic_family(e.access_token)
                try:
                    from agent.anthropic_credentials import _is_oauth_token  # noqa: E402
                    sent_as = "oauth" if _is_oauth_token(e.access_token) else "api_key"
                except Exception:
                    sent_as = None
                console = bool(fam and fam.startswith("console key"))
                auth_mode = {"family": fam, "sent_as": sent_as, "stored_as": e.auth_type,
                             "mismatch": bool(console and sent_as == "oauth")}
            out.append({
                "provider": provider, "id": e.id, "label": e.label, "auth_type": e.auth_type, "source": e.source,
                "expiry": expiry, "auth_mode": auth_mode,
                "status": "dead" if e.last_status == cp.STATUS_DEAD else "benched" if benched else "ok" if not cooled else "model-cooldown",
                "last_status": e.last_status, "error_code": e.last_error_code, "error_reason": e.last_error_reason,
                "failure_reason": (e.extra or {}).get("failure_reason") or getattr(e, "failure_reason", None),
                "error_message": (e.last_error_message or "")[:200] or None,
                "benched_until": until if benched else None,
                "stale_bench": e.last_status == cp.STATUS_EXHAUSTED and not benched,
                "model_cooldowns": cooled, "sole_credential": len(live) == 1,
            })
            by_pool.setdefault(provider, []).append((e, benched))

    def reach(provider: str | None, base_url: str | None, model: str | None) -> dict:
        """Can a request for this model on this provider find a usable login right now?"""
        provider = (provider or "").strip()
        if not provider:
            return {"verdict": "unknown", "reason": "no provider set"}
        try:
            key = cp.resolve_runtime_pool_key(provider, base_url) or provider.lower()
        except Exception:
            key = provider.lower()
        entries = by_pool.get(key, [])
        if not entries:
            # Nothing pooled: Hermes may still use a key from .env/config or a provider sign-in. Not a red flag.
            return {"pool": key, "logins": 0, "usable": 0, "verdict": "unpooled"}
        usable, blocking = [], []
        for e, benched in entries:
            until = model_cooldown_until(e, model) if model else None
            if e.last_status == cp.STATUS_DEAD or benched or (until and until > now):
                blocking.append(e.id)
            else:
                usable.append(e.id)
        verdict = "blocked" if not usable else "no-backup" if len(entries) == 1 else "ok"
        return {"pool": key, "logins": len(entries), "usable": len(usable), "blocking": blocking, "verdict": verdict}

    model_cfg: dict = {}
    fallback_cfg: list = []
    try:
        from hermes_cli.config import load_config  # noqa: E402
        config = load_config()
        raw = config.get("model")
        model_cfg = raw if isinstance(raw, dict) else {"default": raw}
        fb = config.get("fallback_model")  # a single dict or a chain (list of dicts)
        fallback_cfg = [x for x in (fb if isinstance(fb, list) else [fb]) if isinstance(x, dict)]
    except Exception:
        model_cfg = {}
    default = {"model": model_cfg.get("default"), "provider": model_cfg.get("provider"), "base_url": model_cfg.get("base_url")}
    default["reach"] = reach(default["provider"], default["base_url"], default["model"])
    default["fallbacks"] = [{"model": f.get("model"), "provider": f.get("provider"), "reach": reach(f.get("provider"), f.get("base_url"), f.get("model"))} for f in fallback_cfg]
    default["covered"] = next((f for f in default["fallbacks"] if f["reach"]["verdict"] in ("ok", "no-backup", "unpooled")), None)

    crons = []
    jobs_file = Path(os.environ["HERMES_HOME"]) / "cron" / "jobs.json"
    try:
        raw_jobs = json.loads(jobs_file.read_text(encoding="utf-8"))
        jobs = raw_jobs.get("jobs", []) if isinstance(raw_jobs, dict) else raw_jobs
    except (OSError, ValueError):
        jobs = []
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict) or job.get("enabled") is False or job.get("paused_at") or job.get("no_agent"):
            continue  # paused, disabled, or a script-only job that never calls a model
        provider = job.get("provider") or default["provider"]
        base_url = job.get("base_url") if job.get("provider") else default["base_url"]
        model = job.get("model") or default["model"]
        crons.append({"id": job.get("id"), "name": job.get("name") or job.get("id"), "next_run_at": job.get("next_run_at"),
                      "model": model, "provider": provider, "reach": reach(provider, base_url, model)})
    # B1b (#97085): an ANTHROPIC_API_KEY in .env can take over from a subscription login and bill the paid API.
    home = Path(os.environ["HERMES_HOME"])
    has_sub = any(c["provider"] == "anthropic" and c["auth_type"] == cp.AUTH_TYPE_OAUTH for c in out)
    env_shadow = "ANTHROPIC_API_KEY" in env_names(home) and has_sub
    return {"credentials": out, "default_model": default, "crons": crons, "env_shadow": env_shadow}


def read_profile(name: str, home: Path) -> dict:
    env = {**os.environ, "HERMES_HOME": str(home)}
    python = AGENT / "venv" / "bin" / "python"
    run = subprocess.run([str(python if python.exists() else sys.executable), __file__, "--one"], env=env, capture_output=True, text=True, timeout=60)
    if run.returncode != 0:
        return {"profile": name, "error": (run.stderr.strip().splitlines() or ["unreadable"])[-1]}
    return {"profile": name, **json.loads(run.stdout)}


def mark_shared(results: list[dict]) -> None:
    """The same pooled login (provider + id) in several profiles: one bench hits every one of them."""
    seen: dict[tuple, list] = {}
    for r in results:
        for c in r.get("credentials", []):
            seen.setdefault((c["provider"], c["id"]), []).append(r["profile"])
    for r in results:
        for c in r.get("credentials", []):
            c["shared_with"] = [p for p in seen[(c["provider"], c["id"])] if p != r["profile"]]


def model_line(profile: str, d: dict) -> str | None:
    """One line on whether the Bot's default model can be reached, or None when nothing is set."""
    if not d or not d.get("provider"):
        return None
    r = d["reach"]
    what = f"{d.get('model') or '?'} via {d['provider']}"
    cover = d.get("covered")
    if r["verdict"] == "blocked" and cover:
        return f"default model {what} BLOCKED; Hermes will fall back to {cover['model']} via {cover['provider']}"
    if r["verdict"] == "no-backup" and cover:
        return f"default model {what}: ok, one login, covered by fallback {cover['model']} via {cover['provider']}"
    if r["verdict"] == "blocked":
        return f"DEFAULT MODEL BLOCKED: {what} — none of {r['logins']} login(s) usable ({', '.join(r['blocking'])}); this is 'no credentials found'"
    if r["verdict"] == "no-backup":
        return f"default model {what}: ok, but only one login (no backup if it gets benched)"
    if r["verdict"] == "unpooled":
        return f"default model {what}: no pooled login (Hermes may use a key from .env or a sign-in)"
    return f"default model {what}: ok ({r['usable']} of {r['logins']} logins usable)"


def single_points(results: list[dict]) -> list[dict]:
    """Logins that several Bots' default models depend on with no second login to rotate to."""
    deps: dict[tuple, dict] = {}
    for r in results:
        d = r.get("default_model") or {}
        reach = d.get("reach") or {}
        if reach.get("verdict") not in ("no-backup", "blocked") or reach.get("logins") != 1 or d.get("covered"):
            continue
        cred = next((c for c in r.get("credentials", []) if c["provider"].lower() == reach.get("pool")), None)
        if cred:
            item = deps.setdefault((cred["provider"], cred["id"]), {"provider": cred["provider"], "id": cred["id"], "label": cred["label"], "bots": []})
            item["bots"].append(r["profile"])
    return [v for v in deps.values() if len(v["bots"]) > 1]


def blocked_crons(r: dict) -> list[dict]:
    return [c for c in r.get("crons", []) if c["reach"].get("verdict") == "blocked"]


# One verdict per login, worst first; the CLI report, the alert, --json and the Desktop page all use it.
STATES = ("dead", "benched", "expired", "wrong-auth-mode", "model-cooldown", "expiring", "stale", "ok")


def state_of(c: dict) -> str:
    if c["status"] in ("dead", "benched"):
        return c["status"]
    exp = (c.get("expiry") or {}).get("state")
    if exp == "expired":
        return "expired"
    if (c.get("auth_mode") or {}).get("mismatch"):
        return "wrong-auth-mode"
    if c["status"] == "model-cooldown":
        return "model-cooldown"
    if exp == "expiring":
        return "expiring"
    if c["stale_bench"]:
        return "stale"
    return "ok"


def note_for(c: dict, now: float) -> str | None:
    """Plain-language line for the two newer checks (A5 expiry, B1 auth mode)."""
    st = state_of(c)
    e = c.get("expiry") or {}
    if st in ("expired", "expiring"):
        return (f"OAuth login {'expired' if st == 'expired' else 'expires'} {when(e.get('expires_at'), now)}"
                " and has no refresh token, so it cannot renew itself")
    if st == "wrong-auth-mode":
        m = c["auth_mode"]
        return (f"this is a {m['family']}, but this Hermes sends it as OAuth (Bearer). Anthropic then answers"
                " 'credit balance too low' even though the key is fine (NousResearch/hermes-agent#133856)")
    return None

def fix_for(profile: str, c: dict) -> str | None:
    # Always explicit: a plain `hermes` follows ~/.hermes/active_profile, which may not be "default".
    flag = f"-p {profile} "
    st = state_of(c)
    if st in ("expired", "expiring"):
        return f"hermes {flag}auth add {c['provider']} --type oauth   # sign in again; then: hermes {flag}auth remove {c['provider']} {c['id']}"
    if st == "wrong-auth-mode":
        return (f"hermes {flag}auth add anthropic --type api-key   # with a standard sk-ant-api key from the Console;"
                f" then: hermes {flag}auth remove anthropic {c['id']}")
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
        bad = [c for c in creds if state_of(c) != "ok"]
        print(f"\n{r['profile']}: {len(creds)} credential(s), {len(bad)} need attention")
        if line := model_line(r["profile"], r.get("default_model")):
            print(f"  {line}")
        if r.get("env_shadow"):
            print("  NOTE: ANTHROPIC_API_KEY is set in this Bot's .env next to a subscription login; Hermes can pick the paid key"
                  " and bill the API instead of your subscription (NousResearch/hermes-agent#97085). Remove it from .env if that is not what you want.")
        for job in blocked_crons(r):
            print(f"  CRON WILL FAIL: {job['name']} (next {job['next_run_at'] or '?'}) — {job['model']} via {job['provider']} has no usable login")
        for c in creds:
            mark = {"ok": "ok ", "benched": "BENCHED", "dead": "DEAD", "model-cooldown": "MODEL COOLDOWN", "expired": "EXPIRED",
                    "expiring": "EXPIRING", "wrong-auth-mode": "WRONG AUTH MODE", "stale": "STALE BENCH"}[state_of(c)]
            print(f"  {mark:<14} {c['provider']:<16} {c['label'][:28]:<28} {c['auth_type']:<7} id={c['id']}")
            if c["status"] == "benched":
                print(f"                 why: {why(c)}; until {when(c['benched_until'], now)}" + (" — the only credential for this provider" if c["sole_credential"] else ""))
            if note := note_for(c, now):
                print(f"                 {note}")
            if c["stale_bench"]:
                print("                 marked exhausted, bench time has passed; Hermes should retry it, a reset makes sure")
            for model, until in c["model_cooldowns"].items():
                print(f"                 {model}: blocked on this credential until {when(until, now)}" + (" — longer than any rate limit; likely the stuck-cooldown bug (NousResearch/hermes-agent#127917)" if until - now > 7 * 86400 else ""))
            if c["status"] != "ok" and c["error_message"]:
                print(f"                 provider said: {c['error_message']}")
            if fix := fix_for(r["profile"], c):
                print(f"                 fix: {fix}")
                if c.get("shared_with"):
                    print(f"                 shared with {len(c['shared_with'])} other Bot(s) ({', '.join(c['shared_with'])}): one fix clears all of them")
        dm = r.get("default_model") or {}
        trouble += len(bad) + len(blocked_crons(r)) + (1 if dm.get("reach", {}).get("verdict") == "blocked" and not dm.get("covered") else 0)
    total = sum(len(r.get("credentials", [])) for r in results)
    for sp in single_points(results):
        print(f"\nRISK: {len(sp['bots'])} Bots run their default model on one {sp['provider']} login ({sp['id']}) with no backup:"
              f" {', '.join(sp['bots'])}. One rate limit on it stops all {len(sp['bots'])}. Add a second login or a fallback model.")
    crons = sum(len(r.get("crons", [])) for r in results)
    print(f"\nChecked {total} credential(s), {len(results)} default model(s) and {crons} active cron job(s) across {len(results)} profile(s): {trouble} need attention.")
    return 1 if trouble else 0


def alert(results: list[dict], now: float) -> str:
    """Short Telegram text for a watchdog cron: empty when every credential is healthy."""
    lines = []
    told: set = set()
    for r in results:
        if "error" in r:
            lines.append(f"• {r['profile']}: could not read ({r['error']})"); continue
        d = r.get("default_model") or {}
        if d.get("reach", {}).get("verdict") == "blocked":
            cover = d.get("covered")
            lines.append(f"• {r['profile']}: default model {d.get('model')} via {d.get('provider')} is blocked" + (f"; running on fallback {cover['model']}" if cover else "; the Bot can't answer"))
        for job in blocked_crons(r):
            lines.append(f"• {r['profile']}: cron '{job['name']}' will fail (next {job['next_run_at'] or '?'}): no usable {job['provider']} login")
        for c in r["credentials"]:
            if state_of(c) == "ok":
                continue
            if (c["provider"], c["id"]) in told:
                continue  # a shared login is reported once, with every Bot it affects
            told.add((c["provider"], c["id"]))
            if c["status"] == "benched":
                what = f"BENCHED, {why(c)}, until {when(c.get('benched_until'), now)}"
            elif c["status"] == "dead":
                what = "DEAD, the provider rejected it"
            elif state_of(c) in ("expired", "expiring", "wrong-auth-mode"):
                what = state_of(c).replace("-", " ").upper() + ": " + note_for(c, now)
            elif c["status"] == "model-cooldown":
                what = "blocked for " + ", ".join(f"{m} until {when(t, now)}" for m, t in c["model_cooldowns"].items())
            else:
                what = "marked exhausted, bench time passed"
            who = r["profile"] + (f" + {len(c.get('shared_with', []))} more Bots" if c.get("shared_with") else "")
            lines.append(f"• {who} · {c['provider']} ({c['label'][:24]}): {what}\n  fix: {fix_for(r['profile'], c)}" + ("  (one fix clears all)" if c.get("shared_with") else ""))
    if not lines:
        return ""
    return f"Key Doctor: {len(lines)} Hermes login(s) need attention\n" + "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Why did my Hermes key stop working?")
    parser.add_argument("-p", "--profile", help="one profile (default: all)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--alert", action="store_true", help="watchdog mode: print only problems, nothing when healthy, always exit 0")
    parser.add_argument("--one", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.one:
        print(json.dumps(inspect_one())); return 0
    targets = [(n, h) for n, h in profiles() if not args.profile or n == args.profile]
    if not targets:
        print(f"No profile named {args.profile}."); return 2
    results = [read_profile(n, h) for n, h in targets]
    mark_shared(results)
    if args.alert:
        text = alert(results, time.time())
        if text:
            print(text)
        return 0
    if args.json:
        print(json.dumps(results, indent=2)); return 0
    return report(results, time.time())


if __name__ == "__main__":
    sys.exit(main())
