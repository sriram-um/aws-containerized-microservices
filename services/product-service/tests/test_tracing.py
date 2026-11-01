from fastapi import FastAPI

from product_service.tracing import setup_tracing


def test_tracing_disabled_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert setup_tracing(FastAPI(), "test") is False
