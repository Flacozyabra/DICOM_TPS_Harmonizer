import io
from pathlib import Path
import struct
import pydicom
from pydicom.dataset import Dataset

def _validate_or_decompress_pixels(ds: Dataset) -> None:
    """Decompress encapsulated PixelData or verify uncompressed PixelData byte length."""
    if not any(tag in ds for tag in ['PixelData', 'FloatPixelData', 'DoubleFloatPixelData']):
        return

    file_meta = getattr(ds, 'file_meta', None)
    ts_uid = getattr(file_meta, 'TransferSyntaxUID', None) if file_meta is not None else None
    is_compressed = bool(ts_uid is not None and ts_uid.is_compressed)
    has_encapsulated = bool(getattr(ds.get('PixelData'), 'is_undefined_length', False))

    if is_compressed or has_encapsulated:
        try:
            ds.decompress()
        except AttributeError:
            pass
        except (ValueError, NotImplementedError) as e:
            msg = str(e).lower()
            if "already uncompressed" not in msg and "not compressed" not in msg:
                raise

    if not is_compressed and 'PixelData' in ds:
        rows = int(getattr(ds, 'Rows', 0) or 0)
        cols = int(getattr(ds, 'Columns', 0) or 0)
        bits = int(getattr(ds, 'BitsAllocated', 0) or 0)
        samples = int(getattr(ds, 'SamplesPerPixel', 1) or 1)
        n_frames = int(getattr(ds, 'NumberOfFrames', 1) or 1)
        if rows > 0 and cols > 0 and bits > 0:
            expected = rows * cols * samples * n_frames * max(1, bits // 8)
            actual = len(ds.PixelData)
            if actual < expected:
                raise ValueError(f"Truncated uncompressed PixelData ({actual} < {expected} bytes)")


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

        if not stop_before_pixels:
            # pydicom 2.4 may silently drop PixelData when (FFFE,E0DD) delimiter is missing
            has_pixel_tag = any(t in ds for t in ('PixelData', 'FloatPixelData', 'DoubleFloatPixelData'))
            is_image_ds = int(getattr(ds, 'Rows', 0) or 0) > 0 and int(getattr(ds, 'Columns', 0) or 0) > 0
            if is_image_ds and not has_pixel_tag:
                raise pydicom.errors.InvalidDicomError("Image dataset missing PixelData; triggering EOF recovery")
            _validate_or_decompress_pixels(ds)

        return ds

    except (pydicom.errors.InvalidDicomError, TypeError, KeyError, ValueError, EOFError, struct.error) as e:
        # Если стандартное чтение не удалось, пробуем применить Siemens EOF Fix
        try:
            with open(file_path, 'rb') as fp:
                data = fp.read()

            # Дописываем маркер конца последовательности пикселей
            fixed_data = data + b'\xfe\xff\xdd\xe0\x00\x00\x00\x00'

            ds = pydicom.dcmread(io.BytesIO(fixed_data), stop_before_pixels=stop_before_pixels, force=True)

            if not hasattr(ds, 'SOPClassUID') or len(ds) == 0:
                raise pydicom.errors.InvalidDicomError("Still missing SOPClassUID after fix")

            if not stop_before_pixels:
                has_pixel_tag = any(t in ds for t in ('PixelData', 'FloatPixelData', 'DoubleFloatPixelData'))
                is_image_ds = int(getattr(ds, 'Rows', 0) or 0) > 0 and int(getattr(ds, 'Columns', 0) or 0) > 0
                if is_image_ds and not has_pixel_tag:
                    raise pydicom.errors.InvalidDicomError("Image dataset still missing PixelData after fix")
                _validate_or_decompress_pixels(ds)

            ds.is_restored = True
            return ds

        except Exception as fix_err:
            raise ValueError(
                f"Не удалось прочитать или восстановить файл DICOM: {file_path.name}. "
                f"Ошибка: {fix_err}"
            ) from e

