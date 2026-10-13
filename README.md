# Hermes Key Doctor

**Why did my Hermes key stop working?**

After a rate limit, a billing error or a model the account isn't entitled to, Hermes quietly *benches* the login that failed, or blocks one model on it. `hermes auth status` still says "logged in". The symptoms are "no credentials found", a `/model` picker that collapsed, or cron jobs that stop.

Key Doctor shows, for every Hermes profile and every pooled login:

- **OK / BENCHED / DEAD / MODEL COOLDOWN**
- **why** (rate limit, billing, forbidden model, expired login) and **until when**
- the **exact command** that clears it (`hermes -p <profile> auth reset <provider> <id>`)

It reads through Hermes's own credential code, so the end times are the ones Hermes enforces. It is read-only and never prints a token.

## Install

```bash
git clone https://github.com/BkashJEE/hermes-key-doctor && cd hermes-key-doctor
cp skills/key-doctor/scripts/key_doctor.py ~/.hermes/scripts/key-doctor.py
cp skills/key-doctor/scripts/key_doctor_alert.py ~/.hermes/scripts/key-doctor-alert.py
mkdir -p ~/.hermes/skills/key-doctor && cp skills/key-doctor/SKILL.md ~/.hermes/skills/key-doctor/
```

Run it:

```bash
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/scripts/key-doctor.py
```

Or ask any bot: *"Check my logins: is anything benched?"*

Daily watchdog (silent when healthy, Telegram when not):

```bash
hermes -p default cron create "10 9 * * *" --name key-doctor-daily --script key-doctor-alert.py --no-agent --deliver telegram
```

Note: a plain `hermes` command follows `~/.hermes/active_profile`, so every fix Key Doctor prints names its profile with `-p`.

## Tests

```bash
python3 -m unittest tests/test_key_doctor.py
```

Related upstream issues: NousResearch/hermes-agent#132817, #127917, #128995, #136687.
