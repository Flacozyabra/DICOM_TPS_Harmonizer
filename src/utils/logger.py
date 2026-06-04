from abc import ABC, abstractmethod
import queue
from typing import Tuple, Union

class BaseLogger(ABC):
    """Абстрактный класс для логирования операций."""

    @abstractmethod
    def log(self, text: str, tag: str = "info") -> None:
        """Записывает текстовое сообщение с определенным тегом.

        Args:
            text: Текст сообщения.
            tag: Тег сообщения (info, warning, error, success).
        """
        pass

    @abstractmethod
    def update_progress(self, current: int, total: int) -> None:
        """Обновляет статус прогресса выполнения операции.

        Args:
            current: Количество обработанных элементов.
            total: Общее количество элементов.
        """
        pass


class QueueLogger(BaseLogger):
    """Потокобезопасный логгер, отправляющий сообщения в очередь queue.Queue."""

    def __init__(self, log_queue: queue.Queue) -> None:
        """Инициализация логгера.

        Args:
            log_queue: Очередь для отправки логов в GUI.
        """
        self.queue = log_queue

    def log(self, text: str, tag: str = "info") -> None:
        """Кладет сообщение лога в очередь."""
        self.queue.put(("log", text, tag))

    def update_progress(self, current: int, total: int) -> None:
        """Кладет данные прогресса в очередь."""
        self.queue.put(("progress", current, total))
