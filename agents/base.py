"""Base agent class — shared LLM calling, prompt building, citation validation."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("agents")


@dataclass
class AgentOutput:
    """Structured output from any agent."""
    agent_id: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    citations: List[Dict[str, str]] = field(default_factory=list)
    reasoning: str = ""
    error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agentId": self.agent_id,
            "success": self.success,
            "data": self.data,
            "citations": self.citations,
            "reasoning": self.reasoning,
            "error": self.error,
            "metrics": self.metrics,
        }


class BaseAgent:
    """Base class for CxU-driven agents."""

    AGENT_ID = "base"
    AGENT_NAME = "Base Agent"

    def __init__(self, config: dict):
        self.config = config
        pipeline = config.get("agentPipeline", {})
        self.model = pipeline.get("model", "claude-sonnet-4-6")
        self.fallback_models = pipeline.get("fallbackModels", [])
        self.temperature = pipeline.get("temperature", 0.05)
        self.max_tokens = pipeline.get("maxTokens", 1000)
        self._last_call_ms = 0

    async def call_llm(
        self, system_prompt: str, user_prompt: str, response_format: str = "json"
    ) -> Optional[dict]:
        """Call LLM with model chain fallback. Returns parsed JSON or None."""
        models = [self.model] + self.fallback_models
        last_error = None

        for model in models:
            try:
                start = time.time()
                result = await self._call_model(model, system_prompt, user_prompt)
                elapsed_ms = (time.time() - start) * 1000
                self._last_call_ms = elapsed_ms

                if result is None:
                    continue

                # Parse JSON from response
                parsed = self._extract_json(result)
                if parsed is not None:
                    parsed["_metrics"] = {
                        "modelName": model,
                        "temperature": self.temperature,
                        "executionTimeMs": round(elapsed_ms),
                    }
                    return parsed

                logger.warning(f"{self.AGENT_ID}: {model} returned non-JSON response")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"{self.AGENT_ID}: {model} failed: {e}")
                continue

        logger.error(f"{self.AGENT_ID}: all models failed. Last error: {last_error}")
        return None

    async def _call_model(self, model: str, system: str, user: str) -> Optional[str]:
        """Call a specific model. Supports Anthropic and OpenAI APIs."""
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")

        if ("claude" in model or "sonnet" in model or "opus" in model or "haiku" in model) and anthropic_key:
            return await self._call_anthropic(model, system, user, anthropic_key)
        elif openai_key:
            return await self._call_openai(model, system, user, openai_key)
        elif anthropic_key:
            # Fallback: use anthropic with whatever model name
            return await self._call_anthropic("claude-sonnet-4-6", system, user, anthropic_key)
        else:
            raise RuntimeError("No LLM API key found (ANTHROPIC_API_KEY or OPENAI_API_KEY)")

    async def _call_anthropic(self, model: str, system: str, user: str, api_key: str) -> Optional[str]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", [])
            if content and content[0].get("type") == "text":
                return content[0]["text"]
        return None

    async def _call_openai(self, model: str, system: str, user: str, api_key: str) -> Optional[str]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0]["message"]["content"]
        return None

    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract JSON from LLM response text."""
        text = text.strip()
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting from markdown code block
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass
        if "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass
        # Try finding JSON object in text
        for i, ch in enumerate(text):
            if ch == "{":
                depth = 0
                for j in range(i, len(text)):
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i : j + 1])
                        except json.JSONDecodeError:
                            break
                break
        return None

    def _make_output(self, data: dict, citations: list, reasoning: str = "", metrics: dict = None) -> AgentOutput:
        return AgentOutput(
            agent_id=self.AGENT_ID,
            success=True,
            data=data,
            citations=citations,
            reasoning=reasoning,
            metrics=metrics or {},
        )

    def _make_error(self, error: str) -> AgentOutput:
        return AgentOutput(
            agent_id=self.AGENT_ID,
            success=False,
            error=error,
        )
