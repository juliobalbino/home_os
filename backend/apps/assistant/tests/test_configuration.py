from django.test import SimpleTestCase, override_settings

from apps.assistant.configuration import assistant_is_ready


class AssistantConfigurationTests(SimpleTestCase):
    @override_settings(ASSISTANT_ENABLED=False, ASSISTANT_ENCRYPTION_KEY="")
    def test_assistant_is_fail_closed_when_disabled(self):
        self.assertFalse(assistant_is_ready())

    @override_settings(ASSISTANT_ENABLED=True, ASSISTANT_ENCRYPTION_KEY="")
    def test_assistant_is_fail_closed_without_encryption_key(self):
        self.assertFalse(assistant_is_ready())

    @override_settings(
        ASSISTANT_ENABLED=True,
        ASSISTANT_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    def test_assistant_requires_explicit_enablement_and_encryption_key(self):
        self.assertTrue(assistant_is_ready())

    @override_settings(
        ASSISTANT_ENABLED=True, ASSISTANT_ENCRYPTION_KEY="not-a-fernet-key"
    )
    def test_assistant_fails_closed_for_invalid_encryption_key(self):
        self.assertFalse(assistant_is_ready())
