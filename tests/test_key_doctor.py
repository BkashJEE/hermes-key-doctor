"""Key Doctor's verdicts and wording, on synthetic credentials (no Hermes install needed)."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "key-doctor" / "scripts"))
import key_doctor as k  # noqa: E402

NOW = time.time()


def cred(**over):
    base = dict(provider="openai-codex", id="281c14", label="device_code", auth_type="oauth", status="ok", stale_bench=False,
                model_cooldowns={}, error_code=None, failure_reason=None, error_reason=None, error_message=None,
                benched_until=None, sole_credential=True)
    return {**base, **over}


class Verdicts(unittest.TestCase):
    def test_every_fix_names_its_profile(self):
        # A plain `hermes` follows ~/.hermes/active_profile, so "default" must be explicit too.
        self.assertTrue(k.fix_for("default", cred(status="benched")).startswith("hermes -p default auth refresh"))
        self.assertTrue(k.fix_for("gary", cred(status="model-cooldown", model_cooldowns={"m": NOW + 60})).startswith("hermes -p gary auth reset"))

    def test_model_cooldown_is_reset_not_refresh(self):
        self.assertIn("auth reset", k.fix_for("ceo", cred(status="model-cooldown", model_cooldowns={"m": NOW + 60})))

    def test_api_key_bench_is_reset(self):
        self.assertEqual(k.fix_for("ceo", cred(auth_type="api_key", status="benched", provider="anthropic", id="a1")), "hermes -p ceo auth reset anthropic a1")

    def test_healthy_needs_no_fix(self):
        self.assertIsNone(k.fix_for("ceo", cred()))

    def test_why_names_the_error_class(self):
        self.assertIn("rate limited", k.why(cred(error_code=429)))
        self.assertIn("billing", k.why(cred(error_code=402)))
        self.assertIn("unverified", k.why(cred(error_code=403, failure_reason="billing_unverified")))
        self.assertIn("entitled", k.why(cred(error_code=403)))


class Alert(unittest.TestCase):
    def test_silent_when_every_credential_is_healthy(self):
        self.assertEqual(k.alert([{"profile": "ceo", "credentials": [cred(), cred(id="x")]}], NOW), "")

    def test_lists_each_problem_with_its_fix(self):
        text = k.alert([{"profile": "gary", "credentials": [
            cred(status="model-cooldown", model_cooldowns={"ornith-1.5-9b": NOW + 3e7}),
            cred(provider="anthropic", id="a1", label="work key", auth_type="api_key", status="benched", error_code=429, benched_until=NOW + 3600),
        ]}], NOW)
        self.assertTrue(text.startswith("Key Doctor: 2 Hermes login(s) need attention"))
        self.assertIn("ornith-1.5-9b", text)
        self.assertIn("hermes -p gary auth reset anthropic a1", text)

    def test_unreadable_profile_is_reported(self):
        self.assertIn("could not read", k.alert([{"profile": "nova", "error": "boom"}], NOW))


if __name__ == "__main__":
    unittest.main()
