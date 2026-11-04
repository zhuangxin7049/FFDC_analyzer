"""Verify SnapDump shares FFDC AI configuration and capacity without JIRA."""
import unittest
from unittest.mock import patch

import app
from ffdc_snapdump import RequestError


class SnapdumpProviderTests(unittest.TestCase):
    def test_uses_current_ffdc_provider_and_releases_capacity(self):
        messages = [{"role": "user", "content": "Check this dump"}]
        with patch.object(app, "acquire_workspace_chat_slot", return_value=True), patch.object(
            app, "release_workspace_chat_slot"
        ) as release, patch.object(app, "wait_for_ai_request_start") as rate, patch.object(
            app, "load_ai_config", return_value=("https://ai.example.test/v1", "test-token", "model")
        ), patch.object(app, "post_json", return_value={"choices": [{"message": {"content": "Evidence [S1]"}}]}) as post:
            result = app.call_snapdump_chat(messages, "Use the provided logs")
        self.assertEqual(result["answer"], "Evidence [S1]")
        self.assertEqual(post.call_args.args[0], "https://ai.example.test/v1/chat/completions")
        self.assertEqual(post.call_args.args[2]["messages"], [{"role": "system", "content": "Use the provided logs"}, *messages])
        rate.assert_called_once()
        release.assert_called_once()

    def test_full_queue_does_not_call_provider(self):
        with patch.object(app, "acquire_workspace_chat_slot", return_value=False), patch.object(
            app, "release_workspace_chat_slot"
        ) as release, patch.object(app, "load_ai_config") as config:
            with self.assertRaises(RequestError) as error:
                app.call_snapdump_chat([], "prompt")
        self.assertEqual(error.exception.status, 429)
        config.assert_not_called()
        release.assert_not_called()

    def test_config_failure_releases_capacity(self):
        with patch.object(app, "acquire_workspace_chat_slot", return_value=True), patch.object(
            app, "release_workspace_chat_slot"
        ) as release, patch.object(app, "load_ai_config", side_effect=RuntimeError("unavailable")):
            with self.assertRaises(RuntimeError):
                app.call_snapdump_chat([], "prompt")
        release.assert_called_once()
