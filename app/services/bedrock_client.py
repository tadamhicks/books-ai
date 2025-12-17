import asyncio
import hashlib
import os
from dataclasses import dataclass
from typing import Optional, Tuple

import boto3
import httpx

from app.config import settings
from app.tracing import get_tracer


YES_NO_PROMPT = (
    "You are validating if a book exists. "
    "Answer strictly with 'yes' or 'no'. "
    "If unsure, answer 'no'.\n\n"
    "Book title: \"{title}\"\n"
    "Author: \"{author_first} {author_last}\""
)

SUMMARY_PROMPT = (
    "Provide a concise 3-5 sentence summary for the book below.\n"
    "Book title: \"{title}\"\n"
    "Author: \"{author_first} {author_last}\"\n"
    "Respond with only the summary text."
)

SUGGEST_PROMPT = (
    "The requested book may not exist. Suggest up to 3 possible intended titles "
    "and authors that are real, based on the provided (possibly incorrect) input. "
    "Return plain text suggestions."
)


@dataclass
class BedrockOutcome:
    exists: bool
    summary: Optional[str] = None
    suggestions: Optional[str] = None


class BedrockClient:
    def __init__(self) -> None:
        self.model_id = settings.bedrock_model_id
        self.client = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
        self.tracer = get_tracer()

    async def _invoke(self, prompt: str, max_tokens: int = 256, temperature: float = 0.0) -> str:
        # If we have a Bedrock API key, use direct HTTP with Bearer auth (no SigV4).
        # See: https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html
        if settings.bedrock_api_key:
            url = f"https://bedrock-runtime.{settings.bedrock_region}.amazonaws.com/model/{self.model_id}/converse"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.bedrock_api_key}",
            }
            payload = {
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
            }
            timeout = httpx.Timeout(connect=5.0, read=settings.bedrock_timeout_seconds, write=5.0, pool=5.0)
            with self.tracer.start_as_current_span("bedrock.converse") as span:
                span.set_attribute("llm.provider", "aws-bedrock")
                span.set_attribute("llm.model", self.model_id)
                span.set_attribute("llm.request.max_tokens", max_tokens)
                span.set_attribute("llm.request.temperature", temperature)
                prompt_preview = prompt[:1024]
                span.set_attribute("llm.request.prompt_preview", prompt_preview)
                span.set_attribute("llm.request.prompt_chars", len(prompt))
                span.set_attribute("llm.request.prompt_sha256", hashlib.sha256(prompt.encode("utf-8")).hexdigest())
                span.add_event(
                    "llm.message",
                    {
                        "role": "user",
                        "index": 0,
                        # Store full content as an event payload (truncate to bound cost).
                        "content": prompt[:16000],
                    },
                )
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    span.set_attribute("http.status_code", resp.status_code)
                    resp.raise_for_status()
                    data = resp.json()

                usage = data.get("usage") or {}
                for k in ("inputTokens", "outputTokens", "totalTokens"):
                    if k in usage:
                        span.set_attribute(f"llm.usage.{k}", int(usage[k]))

                message = (data.get("output") or {}).get("message") or {}
                content = message.get("content") or []
                if not content:
                    return ""
                first = content[0] or {}
                text = first.get("text", "") or ""
                span.set_attribute("llm.response.chars", len(text))
                span.set_attribute("llm.response.sha256", hashlib.sha256(text.encode("utf-8")).hexdigest())
                span.set_attribute("llm.response.preview", text[:1024])
                span.add_event(
                    "llm.response",
                    {
                        "index": 0,
                        "content": text[:16000],
                    },
                )
                return text

        # Fallback: use boto3 with AWS credentials (SigV4).
        def call_model() -> str:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            )
            message = (response.get("output") or {}).get("message") or {}
            content = message.get("content") or []
            if not content:
                return ""
            first = content[0] or {}
            return first.get("text", "") or ""

        return await asyncio.wait_for(asyncio.to_thread(call_model), timeout=settings.bedrock_timeout_seconds)

    async def check_existence(self, title: str, author_first: str, author_last: str) -> bool:
        prompt = YES_NO_PROMPT.format(title=title, author_first=author_first, author_last=author_last)
        with self.tracer.start_as_current_span("bedrock.check_existence") as span:
            span.set_attribute("llm.model_id", self.model_id)
            span.set_attribute("book.title", title)
            span.set_attribute("book.author_first_name", author_first)
            span.set_attribute("book.author_last_name", author_last)
            text = await self._invoke(prompt, max_tokens=4, temperature=0.0)
            span.set_attribute("llm.response", text)
            normalized = text.strip().lower()
            result = normalized.startswith("yes")
            span.set_attribute("book.exists", result)
            return result

    async def fetch_summary_or_suggestions(
        self, title: str, author_first: str, author_last: str, exists: bool
    ) -> Tuple[Optional[str], Optional[str]]:
        prompt = (
            SUMMARY_PROMPT.format(title=title, author_first=author_first, author_last=author_last)
            if exists
            else SUGGEST_PROMPT + f"\nTitle: {title}\nAuthor: {author_first} {author_last}"
        )
        span_name = "bedrock.summary" if exists else "bedrock.suggestions"
        with self.tracer.start_as_current_span(span_name) as span:
            span.set_attribute("llm.model_id", self.model_id)
            span.set_attribute("book.title", title)
            span.set_attribute("book.author_first_name", author_first)
            span.set_attribute("book.author_last_name", author_last)
            text = await self._invoke(prompt, max_tokens=256, temperature=0.2)
            span.set_attribute("llm.response", text)
            if exists:
                return text.strip(), None
            return None, text.strip() if text else None

    async def evaluate(self, title: str, author_first: str, author_last: str) -> BedrockOutcome:
        exists = await self.check_existence(title, author_first, author_last)
        summary, suggestions = await self.fetch_summary_or_suggestions(title, author_first, author_last, exists)
        return BedrockOutcome(exists=exists, summary=summary, suggestions=suggestions)



