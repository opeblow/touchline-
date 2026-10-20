"""Observability: OpenTelemetry → Azure Monitor (Application Insights) + Agent Framework GenAI spans.

When APPLICATIONINSIGHTS_CONNECTION_STRING is set (the same App Insights resource that is
connected to the Microsoft Foundry project), every agent invocation, model call, token count
and workflow step is exported, so traces appear in Foundry's tracing view and App Insights.
OTEL_EXPORTER_OTLP_ENDPOINT also works (e.g. the AI Toolkit trace viewer in VS Code).
"""

from __future__ import annotations

import logging
import os

from touchline.config import Settings

log = logging.getLogger(__name__)


def configure(settings: Settings) -> bool:
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("agent_framework").setLevel(logging.WARNING)  # per-superstep logs are noisy
    enabled = False
    if settings.applicationinsights_connection_string:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(
                connection_string=settings.applicationinsights_connection_string, logger_name="touchline"
            )
            enabled = True
            log.info("Azure Monitor OpenTelemetry enabled")
        except Exception as exc:  # pragma: no cover
            log.warning("Azure Monitor not enabled: %s", exc)
    elif os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        try:
            from agent_framework.observability import configure_otel_providers

            configure_otel_providers(service_name="touchline")
            enabled = True
        except Exception as exc:  # pragma: no cover
            log.warning("OTLP export not enabled: %s", exc)
    if enabled:
        try:
            from agent_framework.observability import enable_instrumentation

            # GenAI semantic-convention spans for agents, chat clients and workflows.
            enable_instrumentation(enable_sensitive_data=False)
        except Exception as exc:  # pragma: no cover
            log.warning("Agent Framework instrumentation not enabled: %s", exc)
    return enabled
