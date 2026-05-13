import unittest

from api.routes import sidebar
from services.app_knowledge_base import lookup_app_knowledge


class AppAgentGuardrailTests(unittest.TestCase):
    def test_capability_query_typo_variant_is_detected(self):
        self.assertTrue(sidebar._looks_like_capability_query("show me your agentic capabilties in MeetSum"))

    def test_generic_meeting_request_is_detected(self):
        self.assertTrue(sidebar._looks_like_generic_meeting_request("can you start a meeting?"))

    def test_speaker_enrollment_request_maps_to_supported_action(self):
        action = sidebar._detect_action_intent("great! first i would like to enroll a new employee speaker")
        self.assertIsNotNone(action)
        self.assertEqual(action["type"], "start_speaker_enrollment")

    def test_action_reply_for_speaker_enrollment_is_deterministic(self):
        reply = sidebar._action_reply({"type": "start_speaker_enrollment", "label": "Start speaker enrollment"})
        self.assertEqual(reply, "I can open speaker enrollment. Click Go on Start speaker enrollment below.")

    def test_normalize_actions_dedupes_and_filters_removed_display_name_action(self):
        normalized = sidebar._normalize_actions(
            [
                {"type": "set_sidebar_label_display_name", "label": "Sidebar label: Display name"},
                {"type": "set_theme_dark", "label": "Set theme to Dark"},
                {"type": "set_theme_dark", "label": "Set theme to Dark"},
            ]
        )
        self.assertEqual(normalized, [{"type": "set_theme_dark", "label": "Set theme to Dark"}])

    def test_knowledge_base_returns_verified_speaker_enrollment_answer(self):
        knowledge = lookup_app_knowledge("how do i enroll a new speaker?")
        self.assertIsNotNone(knowledge)
        self.assertEqual(knowledge["id"], "speaker_enrollment")
        self.assertIn("Speaker enrollments", knowledge["answer"])
        self.assertIn(
            {"type": "start_speaker_enrollment", "label": "Start speaker enrollment"},
            knowledge["actions"],
        )

    def test_knowledge_base_returns_verified_settings_answer(self):
        knowledge = lookup_app_knowledge("what settings can i change in meetsum?")
        self.assertIsNotNone(knowledge)
        self.assertEqual(knowledge["id"], "user_settings")
        self.assertIn("theme, app language, spoken language, and sidebar label mode", knowledge["answer"])

    def test_knowledge_base_returns_truthful_notes_answer(self):
        knowledge = lookup_app_knowledge("can i create notes?")
        self.assertIsNotNone(knowledge)
        self.assertEqual(knowledge["id"], "notes_and_summaries")
        self.assertIn("does not currently expose a standalone chat action to create notes directly", knowledge["answer"])
        self.assertIn({"type": "start_meeting", "label": "Start a live meeting"}, knowledge["actions"])
        self.assertIn({"type": "upload_meeting", "label": "Upload a meeting recording"}, knowledge["actions"])

    def test_notes_question_counts_as_in_app_request(self):
        self.assertTrue(sidebar._looks_like_in_app_request("can i create notes?"))

    def test_knowledge_base_returns_workspace_unverified_answer(self):
        knowledge = lookup_app_knowledge("can i create a workspace?")
        self.assertIsNotNone(knowledge)
        self.assertEqual(knowledge["id"], "workspace_management")
        self.assertIn("do not have a verified MeetSum workspace-management flow", knowledge["answer"])
        self.assertEqual(knowledge["actions"], [])

    def test_workspace_question_counts_as_in_app_request(self):
        self.assertTrue(sidebar._looks_like_in_app_request("can i create a workspace?"))

    def test_workspace_question_counts_as_agentic_request(self):
        self.assertTrue(sidebar._looks_like_agentic_request("can i create a workspace?"))

    def test_general_non_agentic_question_not_flagged_as_agentic(self):
        self.assertFalse(sidebar._looks_like_agentic_request("what is the weather today?"))

    def test_unknown_agentic_reply_template_is_explicit(self):
        self.assertIn("do not have a verified MeetSum answer", sidebar._AGENTIC_UNKNOWN_REPLY_TEXT)
        self.assertIn("supported in-app actions", sidebar._AGENTIC_UNKNOWN_REPLY_TEXT)

    def test_unknown_query_has_no_verified_knowledge_entry(self):
        knowledge = lookup_app_knowledge("how does meetsum calculate semantic confidence bands?")
        self.assertIsNone(knowledge)


if __name__ == "__main__":
    unittest.main()