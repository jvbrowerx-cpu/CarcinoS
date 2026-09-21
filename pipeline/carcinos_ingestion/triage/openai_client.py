"""
Thin OpenAI client wrapper for structured-outputs calls (spec §3).

Uses the modern Responses API with json_schema response_format, which
enforces the schema at the API layer — eliminating "extra keys" or
malformed-JSON failure modes.

Falls back gracefully if `openai` is not installed (raises a clear error
at call time, not at import time, so disease-site config can still be
loaded for testing).
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class StructuredResult:
    parsed: dict
    raw_response_id: str
    model: str
    usage: dict


class OpenAIClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        triage_model: str = "gpt-4o-mini",
        deep_review_model: str = "gpt-4o-mini",
    ):
        try:
            from openai import OpenAI    # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "openai package is not installed. Run `pip install openai>=1.40`."
            ) from e

        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to your .env or environment."
            )
        self._client = OpenAI(api_key=api_key)
        self.triage_model = triage_model
        self.deep_review_model = deep_review_model

    # ------------------------------------------------------------------
    # Generic structured call
    # ------------------------------------------------------------------

    def structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict,
        temperature: float = 0.0,
    ) -> StructuredResult:
        """
        Call OpenAI Chat Completions with json_schema response_format.

        We use chat.completions.create (not the new Responses API) for
        wider model support; structured output is supported on the gpt-5
        family and gpt-4o snapshots via response_format={"type":"json_schema",...}.

        Note: gpt-5 reasoning models only accept the default temperature (1).
        Passing temperature=0 to them returns a 400 error, so we omit the
        parameter for any non-gpt-4 model and only send it where it is honored.
        """
        kwargs = dict(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": schema,
            },
        )
        # Only legacy gpt-4 / gpt-3.5 models reliably honor a custom temperature.
        # gpt-5 reasoning models reject any value other than the default.
        if model.startswith(("gpt-4", "gpt-3")):
            kwargs["temperature"] = temperature

        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        content = choice.message.content or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"OpenAI returned non-JSON despite schema: {content[:500]}") from e

        return StructuredResult(
            parsed=parsed,
            raw_response_id=resp.id,
            model=resp.model,
            usage={
                "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(resp.usage, "completion_tokens", 0),
                "total_tokens": getattr(resp.usage, "total_tokens", 0),
            },
        )

    # ------------------------------------------------------------------
    # Web search (Responses API with web_search_preview tool)
    # ------------------------------------------------------------------

    def web_search(
        self,
        prompt: str,
        model: str = "gpt-4o-mini-search-preview",
    ) -> str:
        """
        Run a web-search-enabled LLM call using the Responses API.

        Returns the raw output text, or "" on any failure.
        The model must support the web_search_preview tool
        (gpt-4o-mini-search-preview or gpt-4o-search-preview).
        Standard gpt-4o / gpt-4o-mini do NOT support this tool.
        """
        import logging
        log = logging.getLogger("carcinos.openai_client")
        try:
            response = self._client.responses.create(
                model=model,
                tools=[{"type": "web_search_preview"}],
                input=prompt,
            )
            return response.output_text or ""
        except Exception as exc:
            err = str(exc)
            log.error("web_search failed (model=%s): %s", model, err)
            # If the primary model is unavailable, try the sibling variant once.
            fallback = (
                "gpt-4o-search-preview" if "mini" in model
                else "gpt-4o-mini-search-preview"
            )
            if fallback == model:
                return ""
            try:
                response = self._client.responses.create(
                    model=fallback,
                    tools=[{"type": "web_search_preview"}],
                    input=prompt,
                )
                return response.output_text or ""
            except Exception as exc2:
                log.error("web_search fallback (model=%s) also failed: %s", fallback, exc2)
                return ""
