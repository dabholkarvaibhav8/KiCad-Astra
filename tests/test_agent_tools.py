import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock

from agent.astra_client import PlannerClient, PlannerError
from agent.tools import PlanFormatError, empty_plan, extract_json, normalize_plan


class AgentToolsTests(unittest.TestCase):
    def test_fenced_json(self):
        fence = chr(96) * 3
        self.assertEqual(
            extract_json(fence + "json\n" + json.dumps(empty_plan()) + "\n" + fence), empty_plan()
        )

    def test_rejects_duplicate_json_keys(self):
        with self.assertRaises(PlanFormatError):
            extract_json('{"x":1,"x":2}')

    def test_rejects_nonfinite_json(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e999"):
            if value == "1e999":
                p = empty_plan()
                p["placements"] = [
                    {
                        "reference": "U1",
                        "x_mm": float("inf"),
                        "y_mm": 1,
                        "rotation_deg": 0,
                        "side": "front",
                        "reason": "",
                    }
                ]
                with self.assertRaises(PlanFormatError):
                    normalize_plan(p)
            else:
                with self.assertRaises(PlanFormatError):
                    extract_json('{"x":' + value + "}")

    def test_rejects_unknown_nested_fields_and_bad_types(self):
        p = empty_plan()
        p["placements"] = [
            {
                "reference": "U1",
                "x_mm": True,
                "y_mm": 1,
                "rotation_deg": 0,
                "side": "front",
                "reason": "",
                "execute": "anything",
            }
        ]
        with self.assertRaises(PlanFormatError):
            normalize_plan(p)
        p = empty_plan()
        p["unresolved"] = "string"
        with self.assertRaises(PlanFormatError):
            normalize_plan(p)

    def test_review_cannot_modify_board(self):
        p = empty_plan()
        p["placements"] = [
            {
                "reference": "U1",
                "x_mm": 1,
                "y_mm": 1,
                "rotation_deg": 0,
                "side": "front",
                "reason": "",
            }
        ]
        with self.assertRaises(PlanFormatError):
            normalize_plan(p, "review")

    def test_incomplete_response_rejected(self):
        mock = Mock()
        mock.responses.create.return_value = NS(
            status="incomplete", output_text=json.dumps(empty_plan()), output=[], usage=None
        )
        client = PlannerClient(client=mock)
        with self.assertRaises(PlannerError):
            client.create_plan(board_state={}, request="review", mode="review")

    def test_refusal_rejected(self):
        mock = Mock()
        mock.responses.create.return_value = NS(
            status="completed",
            output_text="",
            output=[NS(content=[NS(type="refusal")])],
            usage=None,
        )
        with self.assertRaises(PlannerError):
            PlannerClient(client=mock).create_plan(board_state={}, request="review", mode="review")

    def test_real_sdk_serializes_responses_request(self):
        import httpx
        from openai import OpenAI

        captured = {}

        def handler(request):
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "resp_test",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": "gpt-6-astra",
                    "output": [
                        {
                            "id": "msg_test",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(empty_plan("review")),
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                },
            )

        sdk = OpenAI(
            api_key="test-only-not-a-real-key",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        client = PlannerClient(client=sdk)
        result = client.create_plan(board_state={}, request="review", mode="review")
        self.assertEqual(result["summary"], "review")
        self.assertFalse(captured["store"])
        self.assertEqual(captured["text"]["format"]["type"], "json_schema")
        self.assertEqual(client.usage["calls"], 1)
        client.close()
