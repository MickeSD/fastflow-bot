import os

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram

logger = structlog.get_logger(__name__)

# --- МЕТРИКИ (Prometheus) ---
VPN_KEYS_CREATED = Counter("vpn_keys_created_total", "Total keys created", ["panel"])
VPN_KEYS_EXTENDED = Counter("vpn_keys_extended_total", "Total keys extended", ["panel"])
API_REQUEST_DURATION = Histogram("panel_api_request_seconds", "API call duration", ["panel_host", "method"])
BOT_ERRORS = Counter("bot_errors_total", "Total unhandled bot errors", ["error_type"])

def setup_observability() -> None:
    """Инициализация метрик и распределенной трассировки (Jaeger)"""
    provider = TracerProvider()

    # Подключаем Jaeger через OTLP HTTP
    # В Docker-сети он будет доступен по имени 'jaeger' и порту 4318
    jaeger_endpoint = os.getenv("OTLP_ENDPOINT", "http://jaeger:4318/v1/traces")
    otlp_exporter = OTLPSpanExporter(endpoint=jaeger_endpoint)

    processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    # Авто-инструментация всех aiohttp запросов
    AioHttpClientInstrumentor().instrument()

    logger.info("Observability успешно инициализирована. Трейсы уходят в Jaeger!")
