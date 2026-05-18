import pytest

from core.exceptions import DecryptionError
from core.security import decrypt_data, encrypt_data


def test_encrypt_decrypt_success() -> None:
    """Тест: Успешное шифрование и расшифровка строки"""
    original_text = "secret_vless_key_123"

    # Шифруем
    encrypted = encrypt_data(original_text)
    assert encrypted != original_text
    assert isinstance(encrypted, str)

    # Расшифровываем
    decrypted = decrypt_data(encrypted)
    assert decrypted == original_text

def test_decrypt_invalid_token() -> None:
    """Тест: Попытка расшифровать мусор вызывает кастомную ошибку"""
    with pytest.raises(DecryptionError, match="Неверный токен шифрования"):
        decrypt_data("random_invalid_string_that_is_not_a_token")

def test_empty_string_handling() -> None:
    """Тест: Обработка пустых строк"""
    assert encrypt_data("") == ""
    assert decrypt_data("") == ""
