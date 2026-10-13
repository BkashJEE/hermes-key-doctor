---
name: key-doctor
description: Explain why a Hermes model key or login stopped working — "no credentials found", a /model picker that collapsed, cron jobs blocked on auth, a valid key failing with "credit balance too low". Lists every pooled credential in every profile with its bench state (benched, dead, per-model cooldown), the reason, when it ends, and the exact `hermes auth reset` command. Read-only; never prints tokens.
---

# Key Doctor

After a 429, a 402 or an entitlement error, Hermes benches the credential that failed and
records it in `auth.json`: `last_status`, the error code and reason, and per-model cooldowns.
`hermes auth list` and `hermes auth status` do not show any of it — a benched key still reads
"logged in" — so the usual symptom is a key that "just stopped working".

## When to use

- The user reports "no credentials found", a missing provider in `/model`, or a bot or cron job
  that suddenly cannot reach a model it used yesterday.
- A valid key is refused with a billing or entitlement error.
- Before and after `hermes update`, as a health check across every profile.

## Run it

```bash
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/skills/key-doctor/scripts/key_doctor.py          # every profile
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/skills/key-doctor/scripts/key_doctor.py -p ceo   # one profile
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/skills/key-doctor/scripts/key_doctor.py --json   # for another tool
```

It exits 1 when anything needs attention, so it can gate a cron job.

## Reading the result

| Mark | Meaning | Fix it prints |
|---|---|---|
| `BENCHED` | Hermes will skip this credential until the time shown. `why` is the provider's error class. | `hermes auth reset <provider> <id>` (OAuth: `auth refresh` first) |
| `MODEL COOLDOWN` | The credential works, but one model is blocked on it until the time shown. A cooldown longer than a week is not a rate limit; it matches the stuck-cooldown bug (NousResearch/hermes-agent#127917). | `hermes auth reset <provider> <id>` |
| `DEAD` | The provider rejected the credential outright. | remove it and add it again |
| stale bench | Marked exhausted, but the time has passed. Hermes should retry it; a reset makes sure. | `hermes auth reset ...` |

## Rules

- Never run the fix commands yourself. Show them to the user and let them choose; a reset makes
  Hermes try the credential again, and a billing block will simply re-bench it.
- Never print, log or paste tokens. The script only reports ids, labels and states.
- It uses Hermes's own credential code (`agent.credential_pool`), so the bench end times are the
  ones Hermes enforces. If Hermes changes that code, rerun it after `hermes update`.
