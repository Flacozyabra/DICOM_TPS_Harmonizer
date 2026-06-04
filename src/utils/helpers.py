import re
from typing import List, Optional, Union
from pydicom.dataset import Dataset

def get_seq_attr(
    frame_info: Optional[Dataset], 
    shared_info: Optional[Dataset], 
    seq_name: str, 
    attr_name: str
) -> Optional[Union[List[Union[float, int, str]], str, int, float, bytes]]:
    """Ищет атрибут сначала в per-frame, а затем в shared последовательностях DICOM.

    Args:
        frame_info: Персональная информация о кадре (PerFrameFunctionalGroupsSequence item).
        shared_info: Общая информация о серии (SharedFunctionalGroupsSequence item).
        seq_name: Имя последовательности (например, 'PlanePositionSequence').
        attr_name: Имя атрибута внутри последовательности (например, 'ImagePositionPatient').

    Returns:
        Значение атрибута, список значений или None, если атрибут не найден.
    """
    if not frame_info and not shared_info:
        return None
        
    seq = (getattr(frame_info, seq_name, None) if frame_info else None) or \
          (getattr(shared_info, seq_name, None) if shared_info else None)
    
    if seq and len(seq) > 0:
        val = getattr(seq[0], attr_name, None)
        if val is not None and hasattr(val, '__iter__') and not isinstance(val, (str, bytes)):
            return list(val)
        return val
    return None

def make_safe_filename(s: Union[str, int, float]) -> str:
    """Удаляет из строки спецсимволы Windows/Linux, делая её безопасной для имени папки.

    Args:
        s: Исходная строка или значение.

    Returns:
        Очищенная строка, пригодная для использования в качестве имени директории.
    """
    s_safe = re.sub(r'[\\/*?:"<>|]', "", str(s))
    s_safe = re.sub(r'\s+', "_", s_safe).strip("_")
    return s_safe if s_safe else "UNKNOWN"
