import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openremote import api  # noqa: E402


class ApiGatewayTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        api.session_manager = api.SessionManager()
        api.session_manager.history_dir = self.temp_dir.name
        os.makedirs(api.session_manager.history_dir, exist_ok=True)
        api._opencode_version_cache = None
        api._claude_version_cache = None
        self.client = TestClient(api.app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_root_exposes_supported_providers(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["version"], "1.1.0")
        self.assertIn("opencode", data["providers"])
        self.assertIn("claude", data["providers"])

    def test_version_reports_opencode_and_claude_versions(self):
        with patch.object(api, "_run_opencode_command", return_value=("1.16.2\n", "", 0)), patch.object(
            api,
            "_run_claude_command",
            return_value=("2.1.168 (Claude Code)\n", "", 0),
        ):
            response = self.client.get("/api/version")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["opencode_version"], "1.16.2")
        self.assertEqual(data["claude_version"], "2.1.168 (Claude Code)")
        self.assertEqual(data["gateway_version"], "1.1.0")

    def test_claude_models_endpoint_returns_aliases(self):
        response = self.client.get("/api/models", params={"provider": "claude"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["provider"], "claude")
        self.assertEqual({model["id"] for model in data["models"]}, {"sonnet", "opus"})

    def test_create_claude_session_and_get_details(self):
        response = self.client.post("/api/sessions", params={"provider": "claude", "work_dir": str(ROOT)})

        self.assertEqual(response.status_code, 200)
        session_id = response.json()["session_id"]

        details = self.client.get(f"/api/sessions/{session_id}")
        self.assertEqual(details.status_code, 200)
        data = details.json()
        self.assertEqual(data["provider"], "claude")
        self.assertEqual(data["work_dir"], str(ROOT.resolve()))
        self.assertIsNone(data["provider_session_id"])

    def test_claude_chat_persists_provider_session_and_uses_resume(self):
        calls = []

        def fake_run_command(args, work_dir=None, timeout=120):
            calls.append(args)
            if "--resume" in args:
                return (
                    json.dumps(
                        {
                            "type": "result",
                            "result": "CTX-926",
                            "session_id": "claude-provider-session",
                        }
                    ),
                    "",
                    0,
                )
            return (
                json.dumps(
                    {
                        "type": "result",
                        "result": "OK",
                        "session_id": "claude-provider-session",
                    }
                ),
                "",
                0,
            )

        with patch.object(api, "_resolve_claude_executable", return_value="claude"), patch.object(
            api,
            "_run_command",
            side_effect=fake_run_command,
        ):
            first = self.client.post(
                "/api/chat",
                json={
                    "provider": "claude",
                    "message": "Remember token CTX-926. Reply OK.",
                    "permission_mode": "bypassPermissions",
                },
            )
            second = self.client.post(
                "/api/chat",
                json={
                    "provider": "claude",
                    "session_id": first.json()["session_id"],
                    "message": "What is the token?",
                    "permission_mode": "bypassPermissions",
                },
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["response"], "OK")
        self.assertEqual(second.json()["response"], "CTX-926")
        self.assertEqual(second.json()["provider_session_id"], "claude-provider-session")
        self.assertIn("--output-format", calls[0])
        self.assertIn("stream-json", calls[0])
        self.assertIn("--verbose", calls[0])
        self.assertIn("--resume", calls[1])
        self.assertIn("claude-provider-session", calls[1])

    def test_claude_stream_returns_text_and_done_events(self):
        def fake_run_command(args, work_dir=None, timeout=120):
            return (
                json.dumps(
                    {
                        "type": "result",
                        "result": "SSE_PASS.",
                        "session_id": "claude-stream-session",
                    }
                ),
                "",
                0,
            )

        with patch.object(api, "_resolve_claude_executable", return_value="claude"), patch.object(
            api,
            "_run_command",
            side_effect=fake_run_command,
        ):
            response = self.client.post(
                "/api/chat/stream",
                json={
                    "provider": "claude",
                    "message": "Reply SSE_PASS.",
                    "permission_mode": "bypassPermissions",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Provider"], "claude")
        self.assertIn('data: {"type": "text"', response.text)
        self.assertIn('"content": "SSE_PASS."', response.text)
        self.assertIn("data: [DONE]", response.text)

    def test_claude_chat_returns_tool_events(self):
        output = "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_read",
                                    "name": "Read",
                                    "input": {"file_path": "README.md"},
                                }
                            ]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_read",
                                    "content": "README contents",
                                }
                            ]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "result": "TOOL_DONE",
                        "session_id": "claude-tool-session",
                    }
                ),
            ]
        )

        with patch.object(api, "_resolve_claude_executable", return_value="claude"), patch.object(
            api,
            "_run_command",
            return_value=(output, "", 0),
        ):
            response = self.client.post(
                "/api/chat",
                json={
                    "provider": "claude",
                    "message": "Read README.md and reply TOOL_DONE.",
                    "permission_mode": "bypassPermissions",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["response"], "TOOL_DONE")
        self.assertEqual(len(data["tools"]), 2)
        self.assertEqual(data["tools"][0]["event_type"], "tool_use")
        self.assertEqual(data["tools"][0]["tool"], "Read")
        self.assertEqual(data["tools"][0]["input"], {"file_path": "README.md"})
        self.assertEqual(data["tools"][1]["event_type"], "tool_result")
        self.assertEqual(data["tools"][1]["status"], "completed")
        self.assertEqual(data["tools"][1]["output"], "README contents")
        self.assertEqual(data["permissions"], [])

    def test_claude_permission_mode_in_system_event_is_not_permission_request(self):
        output = "\n".join(
            [
                json.dumps(
                    {
                        "type": "system",
                        "subtype": "init",
                        "session_id": "claude-no-permission-session",
                        "permissionMode": "bypassPermissions",
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "result": "NO_PERMISSION_EVENT",
                        "session_id": "claude-no-permission-session",
                    }
                ),
            ]
        )

        with patch.object(api, "_resolve_claude_executable", return_value="claude"), patch.object(
            api,
            "_run_command",
            return_value=(output, "", 0),
        ):
            response = self.client.post(
                "/api/chat",
                json={
                    "provider": "claude",
                    "message": "Reply NO_PERMISSION_EVENT.",
                    "permission_mode": "bypassPermissions",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["response"], "NO_PERMISSION_EVENT")
        self.assertEqual(data["permissions"], [])

    def test_claude_permission_events_are_returned_and_streamed(self):
        output = "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_bash",
                                    "name": "Bash",
                                    "input": {"command": "git push"},
                                }
                            ]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_bash",
                                    "is_error": True,
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Permission denied: Bash(git push) requires approval.",
                                        }
                                    ],
                                }
                            ]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "error",
                        "is_error": True,
                        "result": "Permission denied: Bash(git push) requires approval.",
                        "session_id": "claude-permission-session",
                    }
                ),
            ]
        )

        with patch.object(api, "_resolve_claude_executable", return_value="claude"), patch.object(
            api,
            "_run_command",
            return_value=(output, "", 0),
        ):
            chat_response = self.client.post(
                "/api/chat",
                json={
                    "provider": "claude",
                    "message": "Run git push.",
                    "permission_mode": "default",
                },
            )
            stream_response = self.client.post(
                "/api/chat/stream",
                json={
                    "provider": "claude",
                    "message": "Run git push.",
                    "permission_mode": "default",
                },
            )

        self.assertEqual(chat_response.status_code, 200)
        data = chat_response.json()
        self.assertEqual(data["provider_session_id"], "claude-permission-session")
        self.assertEqual(data["permissions"][0]["status"], "permission_denied")
        self.assertEqual(data["permissions"][0]["tool"], "Bash")
        self.assertTrue(data["tools"][1]["requires_approval"])
        self.assertEqual(data["tools"][1]["status"], "permission_denied")
        self.assertIn("Permission denied", data["error"])

        self.assertEqual(stream_response.status_code, 200)
        self.assertIn('data: {"type": "permission"', stream_response.text)
        self.assertIn('"status": "permission_denied"', stream_response.text)
        self.assertIn('data: {"type": "tool"', stream_response.text)
        self.assertIn('"requires_approval": true', stream_response.text)
        self.assertIn('"permissions": [', stream_response.text)

    def test_opencode_error_event_is_exposed_as_gateway_error(self):
        error_event = {
            "type": "error",
            "error": {
                "name": "APIError",
                "data": {
                    "message": "Insufficient Balance",
                },
            },
        }

        with patch.object(api, "_resolve_opencode_executable", return_value="opencode"), patch.object(
            api,
            "_run_command",
            return_value=(json.dumps(error_event), "", 0),
        ):
            response = self.client.post(
                "/api/chat",
                json={
                    "provider": "opencode",
                    "message": "Reply OPENCODE_PASS.",
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "opencode chat failed: Insufficient Balance")

    def test_history_can_be_read_and_cleared(self):
        def fake_run_command(args, work_dir=None, timeout=120):
            return (
                json.dumps(
                    {
                        "type": "result",
                        "result": "API_OK",
                        "session_id": "claude-history-session",
                    }
                ),
                "",
                0,
            )

        with patch.object(api, "_resolve_claude_executable", return_value="claude"), patch.object(
            api,
            "_run_command",
            side_effect=fake_run_command,
        ):
            chat_response = self.client.post(
                "/api/chat",
                json={
                    "provider": "claude",
                    "message": "Reply API_OK.",
                    "permission_mode": "bypassPermissions",
                },
            )

        session_id = chat_response.json()["session_id"]
        history_response = self.client.get(f"/api/sessions/{session_id}/history")
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(history_response.json()["count"], 2)

        clear_response = self.client.delete(f"/api/sessions/{session_id}/history")
        self.assertEqual(clear_response.status_code, 200)

        history_after_clear = self.client.get(f"/api/sessions/{session_id}/history")
        self.assertEqual(history_after_clear.json()["count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
