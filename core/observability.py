import os
import re
from typing import Sequence

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ReadableSpan,
    SpanExporter,
    SpanExportResult,
)
from prometheus_client import Counter, Histogram

logger = structlog.get_logger(__name__)

# --- МЕТРИКИ (Prometheus) ---
VPN_KEYS_CREATED = Counter("vpn_keys_created_total", "Total keys created", ["panel"])
VPN_KEYS_EXTENDED = Counter("vpn_keys_extended_total", "Total keys extended", ["panel"])
API_REQUEST_DURATION = Histogram("panel_api_request_seconds", "API call duration", ["panel_host", "method"])
BOT_ERRORS = Counter("bot_errors_total", "Total unhandled bot errors", ["error_type"])
PANEL_CB_TRIPS = Counter("panel_breaker_trips_total", "Circuit Breaker trips", ["panel_host"])

class SanitizingSpanExporter(SpanExporter):
    """Защищенный экспортер-обертка для фильтрации персональных данных из трейсов перед отправкой в Jaeger."""
    def __init__(self, base_exporter: SpanExporter):
        self.base_exporter = base_exporter

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            # 1. Очищаем имя спана (тут может фигурировать UUID или email в URL запроса панели)
            if span._name:
                span._name = self._sanitize_text(span._name)

            # 2. Очищаем атрибуты спана (HTTP URL, метод, хост и т.д.)
            if hasattr(span, "_attributes") and span._attributes:
                try:
                    for key, value in list(span._attributes.items()):
                        if isinstance(value, str):
                            try:
                                # WARNING: relies on internal OTel API, monitor on upgrades!
                                span._attributes[key] = self._sanitize_text(value)  # type: ignore[index]
                            except (TypeError, AttributeError):
                                # OTel SDK изменил API на неизменяемые Mapping, пропускаем, чтобы не крашить приложение
                                pass
                except Exception:
                    pass
        return self.base_exporter.export(spans)

    def _sanitize_text(self, text: str) -> str:
        """Удаляет чувствительные паттерны по аналогии с санитизатором логов."""
        # Маскируем UUID ключей
        text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "***-UUID-***", text)
        # Маскируем vless конфигурации
        text = re.sub(r"(vless://)[^@]+(@)", r"\1***\2", text)
        # Маскируем системные почты пользователей на панелях
        text = re.sub(r"user_\d+(_[0-9a-fA-Za-z]+)?", "user_***_masked", text)
        return text

    def shutdown(self) -> None:
        self.base_exporter.shutdown()

def setup_observability() -> None:
    """Инициализация метрик и распределенной трассировки (Jaeger)"""
    provider = TracerProvider()

    # Подключаем Jaeger через OTLP HTTP
    # В Docker-сети он будет доступен по имени 'jaeger' и порту 4318
    jaeger_endpoint = os.getenv("OTLP_ENDPOINT", "http://jaeger:4318/v1/traces")
    raw_exporter = OTLPSpanExporter(endpoint=jaeger_endpoint)

    # ✅ Оборачиваем базовый экспортер в наш защитный санитизатор секретов
    protected_exporter = SanitizingSpanExporter(raw_exporter)

    processor = BatchSpanProcessor(protected_exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    # Авто-инструментация всех aiohttp запросов
    AioHttpClientInstrumentor().instrument()

    logger.info("Observability успешно инициализирована. Трейсы очищаются от секретов на лету и уходят в Jaeger!")
