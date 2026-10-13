# Hermes Key Doctor

Why did my Hermes key stop working? A read-only skill that shows, for every Hermes profile, which model credentials are benched, dead or blocked for one model, why, until when, and the exact `hermes auth reset` command that clears it.

`hermes auth status` says "logged in" for a credential Hermes is quietly skipping. Key Doctor reads the same state through Hermes's own credential code and prints it.

See `skills/key-doctor/SKILL.md`.
