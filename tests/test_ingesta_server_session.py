"""Session/conversation isolation for /api/chat (Phase 2: conversation_id
replaces request.remote_addr as the analyst conversation-state key)."""
import unittest
from unittest.mock import patch

from scripts import ingesta_server
from tools.analyst.conversation_state import clear_state


class TestConversationIdSessionKey(unittest.TestCase):
    def setUp(self):
        ingesta_server.app.config["TESTING"] = True
        self.client = ingesta_server.app.test_client()
        clear_state("conv-a")
        clear_state("conv-b")

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "X-Ingesta-Token": ingesta_server.API_TOKEN,
        }

    @patch("tools.db_chat.answer")
    def test_conversation_id_from_body_used_as_session_key(self, mock_answer):
        mock_answer.return_value = {"answer_md": "ok", "sql": None, "columns": [], "rows": []}
        self.client.post(
            "/api/chat",
            json={"question": "hola", "history": [], "conversation_id": "conv-a"},
            headers=self._headers(),
        )
        self.assertEqual(mock_answer.call_args.kwargs.get("session_id"), "conv-a")

    @patch("tools.db_chat.answer")
    def test_two_conversation_ids_stay_isolated(self, mock_answer):
        mock_answer.return_value = {"answer_md": "ok", "sql": None, "columns": [], "rows": []}
        self.client.post(
            "/api/chat",
            json={"question": "vacancia de PT", "history": [], "conversation_id": "conv-a"},
            headers=self._headers(),
        )
        self.client.post(
            "/api/chat",
            json={"question": "hola", "history": [], "conversation_id": "conv-b"},
            headers=self._headers(),
        )
        session_ids = [c.kwargs.get("session_id") for c in mock_answer.call_args_list]
        self.assertEqual(session_ids, ["conv-a", "conv-b"])
        self.assertNotEqual(session_ids[0], session_ids[1])

    @patch("tools.db_chat.answer")
    def test_missing_conversation_id_falls_back_to_remote_addr(self, mock_answer):
        mock_answer.return_value = {"answer_md": "ok", "sql": None, "columns": [], "rows": []}
        self.client.post(
            "/api/chat",
            json={"question": "hola", "history": []},
            headers=self._headers(),
        )
        used = mock_answer.call_args.kwargs.get("session_id")
        self.assertTrue(used)  # falls back to something (remote_addr), not empty/None


if __name__ == "__main__":
    unittest.main()
