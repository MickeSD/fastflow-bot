class AppError(Exception):
    """Базовое исключение приложения (от него наследуются остальные)"""
    pass

class PanelAPIError(AppError):
    """Ошибка логики при работе с API панели (например, 401, 403, 500)"""
    pass

class PanelOfflineError(PanelAPIError):
    """Сетевая ошибка: панель недоступна по таймауту или отказала в соединении"""
    pass

class DatabaseError(AppError):
    """Ошибки при выполнении SQL-запросов (пока задел на будущее)"""
    pass

class DecryptionError(AppError):
    """Ошибка расшифровки секьюрных данных (Fernet)"""
    pass
