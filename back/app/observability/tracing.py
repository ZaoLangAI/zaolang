"""OpenTelemetry setup.

Instrumentation is always installed; only the exporter is configurable. That
way spans exist in every environment and turning on a collector is a config
change rather than a code change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.config import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

_configured = False


def configure_tracing(app: FastAPI | None = None) -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    if settings.otel_exporter == "none":
        _configured = True
        return

    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": "zaolang-back", "service.version": settings.app_version}
        )
    )
    if settings.otel_exporter == "otlp" and settings.otel_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
        )
    elif settings.app_env not in ("test", "ci"):
        # Console export is far too noisy inside a test run.
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz,/readyz")

    _configured = True


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
