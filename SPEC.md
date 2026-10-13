# Key Doctor — what it does and what it checks

**One job:** answer *"why did my Hermes key stop working, and what do I type to fix it?"* for every Bot, before the user has to ask.

Users describe the same few symptoms, and none of them name the cause:

- "no credentials found"
- the `/model` picker collapsed
- a cron job failed overnight
- "credit balance too low" on a key that has credit

Hermes already records the cause in each profile's login pool, config and cron jobs. Key Doctor reads those records and turns them into a verdict, a reason and a fix.

## Rules (always)

1. **Read-only.** It never changes a login, a config or a job. It prints the fix; the user runs it.
2. **Never shows a secret.** No token, key or refresh token is printed, logged or sent. Keys are classified by prefix shape only, and email labels are masked on screen.
3. **Hermes's own logic.** Bench times, auth modes and pool lookups come from Hermes's code, not a copy of it, so the doctor never disagrees with what Hermes will actually do.
4. **Every fix names its profile** (`hermes -p <profile> …`), because a plain `hermes` follows `active_profile`.
5. **Honest limits.** Without a live probe it reports what Hermes saved, not whether the provider would accept the key today.

## Checks

Status: ✅ built · 🔜 next · 💡 later

### A. Is each login usable right now?
| # | Check | Verdict | Fix | Status |
|---|---|---|---|---|
| A1 | Benched after an error (`last_status=exhausted`, bench not over) | **BENCHED** + why (429 rate limit / 402 billing / 403 forbidden / 401 expired) + until when | `auth reset` (OAuth: `auth refresh`) | ✅ |
| A2 | One model blocked on a working login (`model_cooldowns`) | **MODEL BLOCKED** + model + until when; over 7 days = stuck-cooldown bug (#127917) | `auth reset` | ✅ |
| A3 | Provider rejected it outright (`last_status=dead`) | **DEAD** | remove and add again | ✅ |
| A4 | Marked exhausted but the time passed | **STALE BENCH** | `auth reset` | ✅ |
| A5 | OAuth token expired or expiring within 24 h, or no refresh token to renew it | **EXPIRING / EXPIRED** + when | `auth refresh` / sign in again | 🔜 |

### B. Is the login the right kind?
| # | Check | Verdict | Fix | Status |
|---|---|---|---|---|
| B1 | Anthropic key shape vs. auth mode: a Console key (`sk-ant-api…`) stored or used as OAuth, or an OAuth token stored as an API key. This is the "credit balance too low on a valid key" report (#136687). | **WRONG AUTH MODE** | re-add with the right type | 🔜 |
| B2 | Custom endpoint login that no longer matches the provider's `base_url` | **POINTS ELSEWHERE** | re-add for that endpoint | 💡 |

### C. Will the Bot actually be able to work?
| # | Check | Verdict | Fix | Status |
|---|---|---|---|---|
| C1 | The Bot's **default model** uses a provider with no usable login (all benched, dead or missing). This is "no credentials found" and the collapsed picker. | **BOT CAN'T REACH ITS MODEL** | the fix for the blocking login, or add one | 🔜 |
| C2 | A **cron job** uses a provider/model with no usable login | **CRON WILL FAIL** + job name + next run | the fix for the blocking login | 🔜 |
| C3 | The provider the Bot depends on has **one login only** (nothing to rotate to) | **NO BACKUP** (info) | add a second login or a fallback model | 🔜 |

### D. How far does one problem reach?
| # | Check | Verdict | Fix | Status |
|---|---|---|---|---|
| D1 | The **same login shared** by several Bots: one bench hits all of them (seen live: one Codex login in 8 of 9 Bots) | **SHARED BY N BOTS** | one reset clears all | 🔜 |
| D2 | Bot Mode keys attached to the wrong Bot (#117325) | **WRONG BOT** | move it | 💡 |

### E. Proof and trend
| # | Check | Verdict | Status |
|---|---|---|---|
| E1 | Optional **live probe** (`--probe`, explicit): one tiny authenticated request per login. It confirms the provider accepts it today and closes the honest-limit gap. It never runs by default, because it spends a request. | **ACCEPTED / REFUSED (code)** | 💡 |
| E2 | **History**: the daily cron appends counts only (no secrets), giving "benched 3 times this week, always on 429" | trend line | 💡 |

## Where it shows

- **Terminal:** `hermes keydoctor` (`--json`, `--alert`) and the standalone script ✅
- **Chat:** `/keys`, and the `key-doctor` skill that bots use when asked ✅
- **Hermes Desktop:** the Key Doctor page plus the `⚿` status chip; Vitals' auth alarm links here ✅
- **Telegram:** the daily `key-doctor-daily` cron, silent when healthy ✅

## Done means

For each 🔜 check:
- a unit test with synthetic logins;
- a run on the real fleet;
- the Desktop page showing it with a Copy fix;
- the alert text naming it.

Nothing ships that prints a secret, changes state, or claims a result the user hasn't seen.
