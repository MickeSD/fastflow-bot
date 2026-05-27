from unittest.mock import MagicMock, patch

from core.observability import SanitizingSpanExporter, setup_observability


def test_sanitize_text() -> None:
    """Тест: Санитизатор успешно прячет секреты"""
    exporter = SanitizingSpanExporter(MagicMock())

    # Проверка маскировки UUID
    res1 = exporter._sanitize_text("request to user 123e4567-e89b-12d3-a456-426614174000")
    assert "***-UUID-***" in res1

    # Проверка маскировки VLESS ключей
    res2 = exporter._sanitize_text("vless://secret_uuid@1.1.1.1:443?sni=host")
    assert "vless://***@1.1.1.1:443" in res2

def test_span_export() -> None:
    """Тест: Экспортер трейсов фильтрует атрибуты перед отправкой"""
    base_mock = MagicMock()
    exporter = SanitizingSpanExporter(base_mock)

    span_mock = MagicMock()
    span_mock._name = "GET 123e4567-e89b-12d3-a456-426614174000"
    span_mock._attributes = {"url": "vless://abc@1.1.1.1:443?sni=a"}

    exporter.export([span_mock])

    assert "***-UUID-***" in span_mock._name
    assert "vless://***" in span_mock._attributes["url"]
    base_mock.export.assert_called_once()

def test_shutdown() -> None:
    """Тест: Экспортер корректно прокидывает команду отключения"""
    base_mock = MagicMock()
    exporter = SanitizingSpanExporter(base_mock)
    exporter.shutdown()
    base_mock.shutdown.assert_called_once()

@patch("core.observability.AioHttpClientInstrumentor")
@patch("core.observability.trace")
def test_setup_observability(mock_trace: MagicMock, mock_instrumentor: MagicMock) -> None:
    """Тест: Успешная инициализация провайдера метрик"""
    setup_observability()
    mock_instrumentor.return_value.instrument.assert_called_once()
    mock_trace.set_tracer_provider.assert_called_once()
