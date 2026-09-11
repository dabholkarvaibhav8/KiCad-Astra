"""Bounded Responses API requests with explicit incomplete/refusal handling."""

from __future__ import annotations

import os

from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from agent.tools import PLAN_JSON_SCHEMA, extract_json, normalize_plan

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-6-astra").strip() or "gpt-6-astra"


class PlannerError(RuntimeError):
    pass


class PlannerClient:
    def __init__(self, *, api_key=None, model=DEFAULT_MODEL, reasoning_effort="high", client=None):
        if reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            raise PlannerError("Unsupported reasoning effort.")
        self.model = model.strip()
        self.reasoning_effort = reasoning_effort
        if client is None:
            key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
            if not key:
                raise PlannerError("Set OPENAI_API_KEY or enter an API key for this session.")
            from openai import OpenAI

            client = OpenAI(api_key=key, timeout=180.0, max_retries=0)
        self._client = client
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def close(self):
        self._client.close()

    def create_plan(
        self,
        *,
        board_state,
        request,
        mode,
        rules=None,
        feedback=None,
        previous_plan=None,
        cancel=None,
    ):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Planning cancelled.")
        prompt = build_user_prompt(
            board_state=board_state,
            request=request,
            mode=mode,
            rules=rules,
            feedback=feedback,
            previous_plan=previous_plan,
        )
        try:
            response = self._client.responses.create(
                model=self.model,
                store=False,
                max_output_tokens=16000,
                reasoning={"effort": self.reasoning_effort},
                input=[
                    {"role": "developer", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "kicad_plan_v2",
                        "strict": True,
                        "schema": PLAN_JSON_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            raise PlannerError(
                f"OpenAI request failed ({status or type(exc).__name__}). Check model access, key, quota and connectivity."
            ) from exc
        self.usage["calls"] += 1
        usage = getattr(response, "usage", None)
        for key in ("input_tokens", "output_tokens"):
            self.usage[key] += getattr(usage, key, 0) or 0
        if cancel is not None and cancel.is_set():
            raise InterruptedError(
                "Planning cancelled. The in-flight API call may still be billed."
            )
        if getattr(response, "status", "completed") != "completed":
            raise PlannerError(f"Response was {response.status}; no partial plan was accepted.")
        for item in getattr(response, "output", []):
            for part in getattr(item, "content", []):
                if getattr(part, "type", "") == "refusal":
                    raise PlannerError("The API declined this planning request.")
        output = getattr(response, "output_text", "")
        if not output:
            raise PlannerError("No complete plan was returned.")
        return normalize_plan(extract_json(output), mode)
