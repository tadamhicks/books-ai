import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import boto3
from opentelemetry import trace

from app.config import settings
from app.tracing import get_tracer, get_meter

logger = logging.getLogger(__name__)


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


def _add_llm_events(span: trace.Span, prompt: str, response: Dict[str, Any], model_id: str) -> None:
    """
    Add OTEL Span Events for LLM request, response, and token usage.

    These appear in Groundcover's "Span Events" tab, matching the standard
    OTEL pattern: https://opentelemetry.io/docs/languages/python/instrumentation/#adding-events

    Events emitted:
      - llm.request  : the prompt sent to the model
      - llm.response : the model's reply text, finish reason
      - llm.token_usage : input / output / total token counts
    """
    # ── llm.request event ─────────────────────────────────────────────
    span.add_event("llm.request", attributes={
        "llm.model_id": model_id,
        "llm.prompt": prompt,
    })

    # ── llm.response event ────────────────────────────────────────────
    output_msg = (response.get("output") or {}).get("message") or {}
    content_blocks = output_msg.get("content") or []
    response_text = ""
    if content_blocks:
        first = content_blocks[0] or {}
        response_text = first.get("text", "") or ""

    span.add_event("llm.response", attributes={
        "llm.model_id": model_id,
        "llm.finish_reason": response.get("stopReason", "unknown"),
        "llm.response.role": output_msg.get("role", "assistant"),
        "content": response_text,
        "index": 0,
    })

    # ── llm.token_usage event ─────────────────────────────────────────
    usage = response.get("usage") or {}
    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)
    span.add_event("llm.token_usage", attributes={
        "llm.model_id": model_id,
        "llm.usage.input_tokens": input_tokens,
        "llm.usage.output_tokens": output_tokens,
        "llm.usage.total_tokens": input_tokens + output_tokens,
    })


class BedrockClient:
    """
    Bedrock client using boto3 with native API Key (Bearer token) authentication.

    Authentication is handled natively by boto3 >= 1.39.0 via the
    AWS_BEARER_TOKEN_BEDROCK environment variable.  The env var is injected
    from a Kubernetes Secret.  AWS_EC2_METADATA_DISABLED=true skips IMDS.

    Observability layers:
      1. OpenLLMetry (Instruments.BEDROCK) auto-creates ``bedrock.converse``
         child spans with token usage / model info as **span attributes**.
      2. This client adds manual **Span Events** (llm.request, llm.response,
         llm.token_usage) on business-logic spans.
      3. Exceptions are recorded on spans via ``span.record_exception()`` and
         the span status is set to ERROR — making failures visible in
         Groundcover's trace waterfall.
      4. Custom OTEL **metrics** (llm.token.usage counter, llm.request.duration
         histogram, books.operations counter) are emitted for dashboards and
         alerting.
      5. Instruments.URLLIB3 propagates traceparent for eBPF correlation.

    Use ``get_bedrock_client()`` to obtain the singleton instance.

    Reference: https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html
    """

    def __init__(self) -> None:
        self.model_id = settings.bedrock_model_id

        if not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
            raise ValueError(
                "AWS_BEARER_TOKEN_BEDROCK environment variable is required but not set. "
                "Ensure the bedrock-api-key secret is configured in the Kubernetes deployment "
                "and the environment variable is properly mapped in k8s/api.yaml."
            )

        self.client = boto3.client(
            service_name="bedrock-runtime",
            region_name=settings.bedrock_region,
        )
        self.tracer = get_tracer()

        meter = get_meter()
        self._token_counter = meter.create_counter(
            "llm.token.usage",
            unit="tokens",
            description="LLM token consumption by model and operation",
        )
        self._llm_duration = meter.create_histogram(
            "llm.request.duration",
            unit="s",
            description="Bedrock converse call latency",
        )
        self._ops_counter = meter.create_counter(
            "books.operations",
            unit="1",
            description="Book operations (check_existence, summary, suggestions, create, delete)",
        )

        logger.info("BedrockClient initialised (model=%s, region=%s)", self.model_id, settings.bedrock_region)

    async def _invoke(
        self, prompt: str, max_tokens: int = 256, temperature: float = 0.0
    ) -> Tuple[str, Dict[str, Any]]:
        """Invoke Bedrock Converse API via boto3.

        Returns ``(response_text, full_response)`` so callers can extract
        token usage and other metadata for span events.
        """
        def call_model() -> Tuple[str, Dict[str, Any]]:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            )
            message = (response.get("output") or {}).get("message") or {}
            content = message.get("content") or []
            text = ""
            if content:
                first = content[0] or {}
                text = first.get("text", "") or ""
            return text, response

        return await asyncio.wait_for(asyncio.to_thread(call_model), timeout=settings.bedrock_timeout_seconds)

    async def check_existence(self, title: str, author_first: str, author_last: str) -> bool:
        """Check if a book exists using Bedrock. Adds span events + domain attributes."""
        prompt = YES_NO_PROMPT.format(title=title, author_first=author_first, author_last=author_last)
        logger.info("Checking existence: '%s' by %s %s", title, author_first, author_last)
        with self.tracer.start_as_current_span("bedrock.check_existence") as span:
            span.set_attribute("book.title", title)
            span.set_attribute("book.author", f"{author_first} {author_last}")
            t0 = time.monotonic()
            try:
                text, response = await self._invoke(prompt, max_tokens=4, temperature=0.0)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                self._ops_counter.add(1, {"operation": "check_existence", "status": "error"})
                logger.error("Bedrock check_existence failed for '%s': %s", title, exc)
                raise
            finally:
                elapsed = time.monotonic() - t0
                self._llm_duration.record(elapsed, {"model_id": self.model_id, "operation": "check_existence"})

            _add_llm_events(span, prompt, response, self.model_id)

            usage = response.get("usage") or {}
            self._token_counter.add(
                usage.get("inputTokens", 0),
                {"model_id": self.model_id, "operation": "check_existence", "direction": "input"},
            )
            self._token_counter.add(
                usage.get("outputTokens", 0),
                {"model_id": self.model_id, "operation": "check_existence", "direction": "output"},
            )

            normalized = text.strip().lower()
            result = normalized.startswith("yes")
            span.set_attribute("book.exists", result)
            self._ops_counter.add(1, {"operation": "check_existence", "status": "ok"})
            logger.info("Existence result for '%s': %s (raw=%r)", title, result, normalized)
            logger.debug("check_existence full response: %s", response)
            return result

    async def fetch_summary_or_suggestions(
        self, title: str, author_first: str, author_last: str, exists: bool
    ) -> Tuple[Optional[str], Optional[str]]:
        """Fetch a book summary or suggestions. Adds span events + domain attributes."""
        prompt = (
            SUMMARY_PROMPT.format(title=title, author_first=author_first, author_last=author_last)
            if exists
            else SUGGEST_PROMPT + f"\nTitle: {title}\nAuthor: {author_first} {author_last}"
        )
        op = "summary" if exists else "suggestions"
        span_name = f"bedrock.{op}"
        logger.info("Fetching %s for '%s' by %s %s", op, title, author_first, author_last)
        with self.tracer.start_as_current_span(span_name) as span:
            span.set_attribute("book.title", title)
            span.set_attribute("book.author", f"{author_first} {author_last}")
            t0 = time.monotonic()
            try:
                text, response = await self._invoke(prompt, max_tokens=256, temperature=0.2)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                self._ops_counter.add(1, {"operation": op, "status": "error"})
                logger.error("Bedrock %s failed for '%s': %s", op, title, exc)
                raise
            finally:
                elapsed = time.monotonic() - t0
                self._llm_duration.record(elapsed, {"model_id": self.model_id, "operation": op})

            _add_llm_events(span, prompt, response, self.model_id)

            usage = response.get("usage") or {}
            self._token_counter.add(
                usage.get("inputTokens", 0),
                {"model_id": self.model_id, "operation": op, "direction": "input"},
            )
            self._token_counter.add(
                usage.get("outputTokens", 0),
                {"model_id": self.model_id, "operation": op, "direction": "output"},
            )

            self._ops_counter.add(1, {"operation": op, "status": "ok"})
            logger.info(
                "Bedrock %s complete: input_tokens=%s output_tokens=%s",
                span_name, usage.get("inputTokens", "?"), usage.get("outputTokens", "?"),
            )
            logger.debug("Bedrock %s full response: %s", op, response)
            if exists:
                return text.strip(), None
            return None, text.strip() if text else None

    async def evaluate(self, title: str, author_first: str, author_last: str) -> BedrockOutcome:
        exists = await self.check_existence(title, author_first, author_last)
        summary, suggestions = await self.fetch_summary_or_suggestions(title, author_first, author_last, exists)
        return BedrockOutcome(exists=exists, summary=summary, suggestions=suggestions)


# ── Module-level singleton ─────────────────────────────────────────
# Avoids creating a new boto3 client (and running the credential chain)
# on every HTTP request.  The client is created lazily on first access.
_bedrock_client: BedrockClient | None = None


def get_bedrock_client() -> BedrockClient:
    """Return the shared BedrockClient singleton."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = BedrockClient()
    return _bedrock_client
