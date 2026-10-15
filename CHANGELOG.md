# Changelog

## 0.2.0 — 2026-10-15

New checks
- **EXPIRING / EXPIRED:** an OAuth sign-in with no refresh token is flagged 24 h before it runs out and after. Sign-ins that renew themselves stay ok.
- **WRONG AUTH MODE:** asks Hermes's own classifier how each Anthropic key will be sent. Console keys (`sk-ant-usr`, `sk-ant-svc`) sent as OAuth are the cause of "credit balance too low" on a valid key (NousResearch/hermes-agent#133856, #136687). Judged by prefix only; the key is never printed.
- **.env billing trap:** `ANTHROPIC_API_KEY` in a Bot's `.env` next to a subscription login (#97085). Only variable names are read.
- **Bot-level checks:** the Bot's default model has no usable login ("no credentials found"), cron jobs that will fail, shared logins and single points of failure. All fallback-aware (`fallback_model`).

Everywhere
- One verdict per login, shared by the terminal report, the Telegram alert, `--json` and the Desktop page.
- README rewritten around the symptoms, with a table of every check and its fix; the Bots' skill guide covers every state.
- 21 tests.

## 0.1.0 — 2026-10-13

- Every pooled login in every profile: OK / BENCHED / DEAD / MODEL COOLDOWN / STALE BENCH, why, until when, and the profile-named fix.
- Hermes Desktop page and `⚿` status chip, `hermes keydoctor` (`--json`, `--alert`), `/keys`.
- Daily watchdog cron, silent when healthy.
