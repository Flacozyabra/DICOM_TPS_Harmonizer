from dataclasses import dataclass

@dataclass(frozen=True)
class ProcessingConfig:
    """Класс данных для хранения настроек процесса оптимизации DICOM.

    Объект неизменяем (frozen=True), что предотвращает случайное изменение настроек
    в процессе обработки в параллельном потоке.
    """
    new_uids: bool
    split_multiframe: bool
    clean_tags: bool
    default_tags: bool
    explicit_vr: bool
    exclude_reports: bool
    split_series: bool
