import structlog
from opentelemetry import trace
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_client import Counter, Histogram

logger = structlog.get_logger(__name__)

# --- МЕТРИКИ (Prometheus) ---
VPN_KEYS_CREATED = Counter("vpn_keys_created_total", "Total keys created", ["panel"])
VPN_KEYS_EXTENDED = Counter("vpn_keys_extended_total", "Total keys extended", ["panel"])
API_REQUEST_DURATION = Histogram("panel_api_request_seconds", "API call duration", ["panel_host", "method"])
BOT_ERRORS = Counter("bot_errors_total", "Total unhandled bot errors", ["error_type"])

def setup_observability() -> None:
    """Инициализация метрик и распределенной трассировки"""
    # 1. Настройка OpenTelemetry (Трассировка)
    provider = TracerProvider()
    # Пока выводим трейсы в консоль (в проде здесь будет OTLPSpanExporter для Jaeger/Zipkin)
    processor = BatchSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    # 2. Авто-инструментация всех aiohttp запросов (внутри PanelAPI)
    AioHttpClientInstrumentor().instrument()

    logger.info("Observability (Metrics & Tracing) успешно инициализирована.")
