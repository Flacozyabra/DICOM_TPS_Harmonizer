import math
import re
from typing import Any, List, Optional, Sequence, Tuple, Union
from pydicom.dataset import Dataset


def _extract_from_seq(container: Optional[Dataset], seq_name: str, attr_name: str) -> Any:
    """Extract an attribute value from the first item of a named sequence."""
    if not container:
        return None
    seq = getattr(container, seq_name, None)
    if seq and len(seq) > 0:
        val = getattr(seq[0], attr_name, None)
        if val is not None:
            if hasattr(val, '__iter__') and not isinstance(val, (str, bytes)):
                return list(val)
            return val
    return None


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

    val = _extract_from_seq(frame_info, seq_name, attr_name)
    if val is not None:
        return val
    return _extract_from_seq(shared_info, seq_name, attr_name)


def first_seq_item(ds: Optional[Dataset], tag: Tuple[int, int]) -> Optional[Dataset]:
    """Return the first item of the DICOM sequence at ``tag``, or ``None``."""
    if ds is None:
        return None
    element = ds.get(tag)
    if element is None or getattr(element, "VR", None) != "SQ":
        return None
    sequence = element.value
    if not sequence:
        return None
    return sequence[0]


def resolve_seq_tag(
    frame_info: Optional[Dataset],
    shared_info: Optional[Dataset],
    top_ds: Optional[Dataset],
    seq_tag: Tuple[int, int],
    elem_tag: Tuple[int, int],
    default: Any = None,
) -> Any:
    """Resolve an element value across per-frame -> shared -> top-level datasets by tag."""
    for container in (frame_info, shared_info):
        item = first_seq_item(container, seq_tag)
        if item is not None and elem_tag in item:
            return item[elem_tag].value
    if top_ds is not None and elem_tag in top_ds:
        return top_ds[elem_tag].value
    return default


def as_floats(value: Any) -> Optional[Tuple[float, ...]]:
    """Convert a DICOM single/multi-valued numeric attribute into a tuple of floats."""
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(",", "\\").split("\\") if p.strip()]
        if not parts:
            return None
        value = parts
    if isinstance(value, (int, float)):
        return (float(value),)
    try:
        result = tuple(float(v) for v in value)
        return result if result else None
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> Optional[int]:
    """Convert a DICOM integer-like value or DataElement into ``int``, or ``None``."""
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compute_slice_normal(orientation: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """Compute the normalized slice normal vector from ImageOrientationPatient (6 cosines)."""
    if not orientation or len(orientation) < 6:
        return None
    try:
        rx, ry, rz = float(orientation[0]), float(orientation[1]), float(orientation[2])
        cx, cy, cz = float(orientation[3]), float(orientation[4]), float(orientation[5])
    except (TypeError, ValueError):
        return None

    nx = ry * cz - rz * cy
    ny = rz * cx - rx * cz
    nz = rx * cy - ry * cx
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if norm <= 1e-12:
        return None
    return (nx / norm, ny / norm, nz / norm)


def compute_slice_location(
    position: Sequence[float],
    orientation: Sequence[float],
) -> Optional[float]:
    """Project ImagePositionPatient onto the unit slice normal and round to 4 decimals."""
    if not position or len(position) < 3:
        return None
    normal = compute_slice_normal(orientation)
    if normal is None:
        return None
    try:
        px, py, pz = float(position[0]), float(position[1]), float(position[2])
    except (TypeError, ValueError):
        return None
    return round(px * normal[0] + py * normal[1] + pz * normal[2], 4)

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
