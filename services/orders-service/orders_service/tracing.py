"""OpenTelemetry tracing -> ADOT collector sidecar -> AWS X-Ray.

Enabled only when OTEL_EXPORTER_OTLP_ENDPOINT is set (the ECS task definition sets it to the
sidecar, http://127.0.0.1:4318). Local runs and unit tests don't trace.
"""
import logging
import os

from fastapi import FastAPI

logger = logging.getLogger("orders_service.tracing")


def setup_tracing(app: FastAPI, service_version: str) -> bool:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False

    from opentelemetry import propagate, trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
    from opentelemetry.propagators.aws import AwsXRayPropagator
    from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    # The ALB adds an X-Amzn-Trace-Id header without a "Sampled" decision, so a parent-based
    # sampler would drop every request. Sample a fixed ratio of trace ids instead.
    ratio = float(os.environ.get("TRACE_SAMPLE_RATIO", "1.0"))
    provider = TracerProvider(
        resource=Resource.create({"service.name": "orders-service", "service.version": service_version}),
        id_generator=AwsXRayIdGenerator(),   # X-Ray trace ids embed the start time
        sampler=TraceIdRatioBased(ratio),
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # endpoint from env + /v1/traces
    trace.set_tracer_provider(provider)
    # X-Amzn-Trace-Id propagation for calls from other instrumented services. (The ALB's own header
    # has only Root= and no Parent=, so requests straight from the ALB start a new trace.)
    propagate.set_global_textmap(AwsXRayPropagator())

    BotocoreInstrumentor().instrument()   # DynamoDB calls become client spans
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health",              # skip health-check noise
        exclude_spans=["send", "receive"],   # one server span per request instead of 3
    )
    logger.info("tracing enabled sample_ratio=%s", ratio)
    return True
