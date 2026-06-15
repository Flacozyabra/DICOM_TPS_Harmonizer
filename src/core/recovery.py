import io
from pathlib import Path
import pydicom
from pydicom.dataset import Dataset

def safe_dcmread(file_path: Path, stop_before_pixels: bool = False) -> Dataset:
    """Безопасно считывает DICOM-файл с диска.

    Если файл поврежден (например, усечен файл Siemens с отсутствующим маркером 
    конца последовательности), функция пытается дописать маркер и повторно распарсить данные.

    Args:
        file_path: Путь к файлу DICOM.
        stop_before_pixels: Если True, останавливает чтение перед тегом пикселей (экономит ОЗУ).

    Returns:
        Объект pydicom.dataset.Dataset.

    Raises:
        ValueError: Если файл не удается прочитать даже после попытки восстановления.
    """
    try:
        # Пробуем стандартное чтение pydicom
        ds = pydicom.dcmread(file_path, stop_before_pixels=stop_before_pixels, force=True)
        
        # Проверяем, корректно ли прочитались метаданные
        if not hasattr(ds, 'SOPClassUID') or len(ds) == 0:
            raise pydicom.errors.InvalidDicomError("Missing SOPClassUID or empty dataset")
            
        return ds
        
    except (pydicom.errors.InvalidDicomError, TypeError, KeyError) as e:
        # Если стандартное чтение не удалось, пробуем применить Siemens EOF Fix
        try:
            with open(file_path, 'rb') as fp:
                data = fp.read()
                
            # Дописываем маркер конца последовательности пикселей
            fixed_data = data + b'\xfe\xff\xdd\xe0\x00\x00\x00\x00'
            
            ds = pydicom.dcmread(io.BytesIO(fixed_data), stop_before_pixels=stop_before_pixels, force=True)
            
            if not hasattr(ds, 'SOPClassUID') or len(ds) == 0:
                raise pydicom.errors.InvalidDicomError("Still missing SOPClassUID after fix")
                
            return ds
            
        except Exception as fix_err:
            raise ValueError(
                f"Не удалось прочитать или восстановить файл DICOM: {file_path.name}. "
                f"Ошибка: {fix_err}"
            ) from e
