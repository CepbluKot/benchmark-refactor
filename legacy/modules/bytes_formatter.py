from typing import Union
def make_readable_bytes(
    value: Union[int, float], decimals: int = 2, per_second: bool = False
) -> str:
    """
    Преобразует число байт/с в человекочитаемую строку.
    - value: число байт в секунду (int или float)
    - binary: True -> 1024-based units (KiB, MiB...), False -> 1000-based (KB, MB...)
    - decimals: число знаков после запятой для формата > B
    - per_second: если True, добавляет "/s" в конец
    """
    if value is None or value < 0:
        return "N/A"
    n = float(value)
    sign = "-" if n < 0 else ""
    n = abs(n)
    step = 1024.0
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    size = n
    i = 0
    while size >= step and i < len(units) - 1:
        size /= step
        i += 1
    # Показать целые байты без дробей (обычно удобнее для B)
    if units[i] == "B":
        # если менее 1 байта/с — показать дробное значение (например 0.50 B/s)
        if size < 1:
            fmt = f"{sign}{size:.{decimals}f} {units[i]}"
        else:
            fmt = f"{sign}{int(round(size)):d} {units[i]}"
    else:
        fmt = f"{sign}{size:.{decimals}f} {units[i]}"
    if per_second:
        fmt += "/s"
    return fmt