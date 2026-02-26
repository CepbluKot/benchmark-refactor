"""
ClickHouse DDL parser & builder.

Парсит CREATE TABLE ... в датаклассы, позволяет менять нужные атрибуты
(тип колонки, кодек, индексы) и пересобирает DDL обратно, сохраняя всё остальное.
"""

import re
from copy import deepcopy
from pydantic import BaseModel, Field, PrivateAttr
from typing import List, Optional, Tuple


# ─── датаклассы ──────────────────────────────────────────────────────────────

class ColumnDef(BaseModel):
    """
    Определение одной колонки.

    Атрибуты для бенчмарка (меняются в ходе тестирования):
        name   — имя колонки
        type   — тип данных
        codec  — CODEC(...) или None

    extra — всё остальное после типа (DEFAULT, TTL, COMMENT, ...),
            сохраняется дословно, бенчмарком не трогается.
    """
    name: str
    type: str
    codec: Optional[str] = None   # e.g. "CODEC(Delta(4), LZ4)"
    extra: str = ""               # DEFAULT expr / TTL / COMMENT / ...

    def to_sql(self, indent: str = "    ") -> str:
        """Рендерит колонку обратно в строку DDL внутри тела CREATE TABLE."""
        parts = [f"`{self.name}`", self.type]
        if self.extra:
            parts.append(self.extra)
        if self.codec:
            parts.append(self.codec)
        return indent + ' '.join(parts)

    def copy(self) -> 'ColumnDef':
        """Возвращает глубокую копию колонки для безопасного мутабельного перебора."""
        return deepcopy(self)


class IndexDef(BaseModel):
    """
    Скипинг-индекс ClickHouse: INDEX name expr TYPE type [GRANULARITY n].

    Атрибуты для бенчмарка:
        name        — имя индекса
        expr        — выражение
        index_type  — тип (minmax, bloom_filter, set, ngrambf_v1, ...)
        granularity — гранулярность (строка)
    """
    name: str
    expr: str
    index_type: str
    granularity: Optional[str] = None
    _raw: str = PrivateAttr(default="")

    def to_sql(self, indent: str = "    ") -> str:
        """Рендерит индекс в строку DDL формата `INDEX ... TYPE ...`."""
        s = f"INDEX {self.name} {self.expr} TYPE {self.index_type}"
        if self.granularity is not None:
            s += f" GRANULARITY {self.granularity}"
        return indent + s

    def copy(self) -> 'IndexDef':
        """Возвращает глубокую копию описания индекса."""
        return deepcopy(self)


class TableDDL(BaseModel):
    """
    Полное определение CREATE TABLE.

    Атрибуты для бенчмарка:
        name         — [db.]table
        cluster      — ON CLUSTER <n>
        columns      — список ColumnDef
        indexes      — список IndexDef
        order_by     — ORDER BY expr
        partition_by — PARTITION BY expr
        primary_key  — PRIMARY KEY expr
        sample_by    — SAMPLE BY expr

    Всё остальное сохраняется дословно:
        engine              — ENGINE = ...
        other_body_entries  — PROJECTION / CONSTRAINT / ... внутри тела
        other_table_options — TTL / SETTINGS / COMMENT / ... после ENGINE
    """
    name: str
    cluster: Optional[str] = None
    columns: List[ColumnDef] = Field(default_factory=list)
    indexes: List[IndexDef] = Field(default_factory=list)
    other_body_entries: List[str] = Field(default_factory=list)
    engine: Optional[str] = None
    partition_by: Optional[str] = None
    order_by: Optional[str] = None
    primary_key: Optional[str] = None
    sample_by: Optional[str] = None
    other_table_options: List[str] = Field(default_factory=list)

    # ── низкоуровневые helpers ────────────────────────────────────────────────

    @staticmethod
    def _skip_line_comment(text: str, i: int) -> int:
        """Сдвигает позицию в конец SQL line-comment `-- ...`."""
        i += 2
        while i < len(text) and text[i] != '\n':
            i += 1
        return i

    @staticmethod
    def _skip_block_comment(text: str, i: int) -> int:
        """Сдвигает позицию после SQL block-comment `/* ... */`."""
        i += 2
        while i + 1 < len(text):
            if text[i] == '*' and text[i + 1] == '/':
                return i + 2
            i += 1
        return len(text)

    @staticmethod
    def _error_preview(text: str, start: int = 0, limit: int = 120) -> str:
        """
        Возвращает короткий фрагмент SQL для диагностик.

        Это убирает «магические» срезы вида `text[:60]` из сообщений ошибок.
        """
        start = max(start, 0)
        if start >= len(text):
            return ""
        chunk = text[start:start + max(limit, 1)]
        if start + len(chunk) < len(text):
            chunk += "..."
        return chunk

    @staticmethod
    def _find_closing_paren(text: str, pos: int) -> int:
        """Возвращает позицию закрывающей скобки для открывающей на pos."""
        assert text[pos] == '(', f"Expected '(' at pos {pos}, got {text[pos]!r}"
        depth = 0
        quote: Optional[str] = None
        i = pos
        while i < len(text):
            ch = text[i]
            if quote is not None:
                if ch == quote:
                    # SQL-экранирование кавычки удвоением ('', "", ``).
                    if i + 1 < len(text) and text[i + 1] == quote:
                        i += 2
                        continue
                    # Поддержка backslash-экранирования.
                    if i > 0 and text[i - 1] == '\\':
                        i += 1
                        continue
                    quote = None
                i += 1
                continue

            if ch in ("'", '"', '`'):
                quote = ch
                i += 1
                continue

            if ch == '-' and i + 1 < len(text) and text[i + 1] == '-':
                i = TableDDL._skip_line_comment(text, i)
                continue
            if ch == '/' and i + 1 < len(text) and text[i + 1] == '*':
                i = TableDDL._skip_block_comment(text, i)
                continue

            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        preview = TableDDL._error_preview(text, start=pos)
        raise ValueError(f"Unbalanced parentheses at pos {pos}: {preview!r}")

    @staticmethod
    def _split_top_level_commas(text: str) -> List[str]:
        """Разбивает строку по запятым верхнего уровня (не внутри скобок)."""
        parts: List[str] = []
        depth = 0
        quote: Optional[str] = None
        buf: List[str] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if quote is not None:
                buf.append(ch)
                if ch == quote:
                    # SQL-экранирование кавычки удвоением ('', "", ``).
                    if i + 1 < len(text) and text[i + 1] == quote:
                        buf.append(text[i + 1])
                        i += 2
                        continue
                    # Поддержка backslash-экранирования.
                    if i > 0 and text[i - 1] == '\\':
                        i += 1
                        continue
                    quote = None
                i += 1
                continue

            if ch in ("'", '"', '`'):
                quote = ch
                buf.append(ch)
                i += 1
                continue

            if ch == '-' and i + 1 < len(text) and text[i + 1] == '-':
                i = TableDDL._skip_line_comment(text, i)
                continue
            if ch == '/' and i + 1 < len(text) and text[i + 1] == '*':
                i = TableDDL._skip_block_comment(text, i)
                continue

            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            if ch == ',' and depth == 0:
                s = ''.join(buf).strip()
                if s:
                    parts.append(s)
                buf = []
            else:
                buf.append(ch)
            i += 1
        s = ''.join(buf).strip()
        if s:
            parts.append(s)
        return parts

    @staticmethod
    def _strip_sql_comments(text: str) -> str:
        """
        Удаляет SQL-комментарии (`-- ...` и `/* ... */`) только вне строк.

        Это защищает значения COMMENT 'foo -- bar' от случайного удаления хвоста строки.
        """
        out: List[str] = []
        quote: Optional[str] = None
        i = 0
        while i < len(text):
            ch = text[i]
            if quote is not None:
                out.append(ch)
                if ch == quote:
                    # SQL-экранирование кавычки удвоением ('', "", ``).
                    if i + 1 < len(text) and text[i + 1] == quote:
                        out.append(text[i + 1])
                        i += 2
                        continue
                    # Поддержка backslash-экранирования.
                    if i > 0 and text[i - 1] == '\\':
                        i += 1
                        continue
                    quote = None
                i += 1
                continue

            if ch in ("'", '"', '`'):
                quote = ch
                out.append(ch)
                i += 1
                continue

            # Комментарии удаляем только вне кавычек.
            if ch == '-' and i + 1 < len(text) and text[i + 1] == '-':
                i = TableDDL._skip_line_comment(text, i)
                continue
            if ch == '/' and i + 1 < len(text) and text[i + 1] == '*':
                i = TableDDL._skip_block_comment(text, i)
                continue

            out.append(ch)
            i += 1
        return ''.join(out)

    @staticmethod
    def _is_top_level_pos(text: str, pos: int) -> bool:
        """
        Возвращает True, если `pos` находится на верхнем уровне SQL-текста.

        Верхний уровень = вне строк/идентификаторов в кавычках и вне скобок.
        """
        depth = 0
        quote: Optional[str] = None
        i = 0
        while i < pos and i < len(text):
            ch = text[i]
            if quote is not None:
                if ch == quote:
                    if i + 1 < len(text) and text[i + 1] == quote:
                        i += 2
                        continue
                    if i > 0 and text[i - 1] == '\\':
                        i += 1
                        continue
                    quote = None
                i += 1
                continue

            if ch in ("'", '"', '`'):
                quote = ch
                i += 1
                continue

            if ch == '-' and i + 1 < len(text) and text[i + 1] == '-':
                i = TableDDL._skip_line_comment(text, i)
                continue
            if ch == '/' and i + 1 < len(text) and text[i + 1] == '*':
                i = TableDDL._skip_block_comment(text, i)
                continue

            if ch == '(':
                depth += 1
            elif ch == ')' and depth > 0:
                depth -= 1
            i += 1
        return quote is None and depth == 0

    @staticmethod
    def _consume_identifier(text: str) -> Tuple[str, str]:
        """Считывает идентификатор (с бэктиками/кавычками или без) с начала строки."""
        text = text.lstrip()
        for q in ('`', '"'):
            if text.startswith(q):
                i = 1
                buf: List[str] = []
                while i < len(text):
                    ch = text[i]
                    if ch == q:
                        # SQL-экранирование кавычки удвоением.
                        if i + 1 < len(text) and text[i + 1] == q:
                            buf.append(q)
                            i += 2
                            continue
                        # Поддержка backslash-экранирования.
                        if i > 0 and text[i - 1] == '\\':
                            buf.append(ch)
                            i += 1
                            continue
                        return ''.join(buf), text[i + 1:].lstrip()
                    buf.append(ch)
                    i += 1
                raise ValueError(
                    f"Unclosed quoted identifier at: {TableDDL._error_preview(text)!r}"
                )
        m = re.match(r'(\w+)(.*)', text, re.DOTALL)
        if m:
            return m.group(1), m.group(2).lstrip()
        raise ValueError(f"Expected identifier at: {TableDDL._error_preview(text)!r}")

    @classmethod
    def _consume_type(cls, text: str) -> Tuple[str, str]:
        """
        Считывает один тип ClickHouse с начала строки (включая вложенные параметры).
        Например: Nullable(String), Array(Tuple(UInt8, String)), LowCardinality(String).
        """
        text = text.lstrip()
        m = re.match(r'(\w+)(.*)', text, re.DOTALL)
        if not m:
            raise ValueError(f"Expected type at: {TableDDL._error_preview(text)!r}")
        name, rest = m.group(1), m.group(2).lstrip()
        if rest.startswith('('):
            end = cls._find_closing_paren(rest, 0)
            return name + rest[:end + 1], rest[end + 1:].lstrip()
        return name, rest

    @classmethod
    def _extract_codec(cls, text: str) -> Tuple[Optional[str], str]:
        """
        Находит и вырезает CODEC(...) из произвольного текста.
        Возвращает (codec_string | None, text_без_codec).
        """
        for m in re.finditer(r'\bCODEC\s*\(', text, re.IGNORECASE):
            if not cls._is_top_level_pos(text, m.start()):
                continue
            paren_pos = m.end() - 1
            end = cls._find_closing_paren(text, paren_pos)
            codec_str = text[m.start():end + 1]
            cleaned = (text[:m.start()] + text[end + 1:]).strip()
            return codec_str, cleaned
        return None, text

    # ── парсинг ──────────────────────────────────────────────────────────────

    @classmethod
    def from_ddl(cls, ddl: str) -> 'TableDDL':
        """Парсит сырой `CREATE TABLE` SQL в структурированный `TableDDL`."""
        # Убираем SQL-комментарии только вне строк.
        ddl = cls._strip_sql_comments(ddl).strip()

        # 1. Заголовок CREATE TABLE
        header_re = re.compile(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
            r'((?:`[^`]+`|"[^"]+"|[\w.]+)+)'
            r'(?:\s+ON\s+CLUSTER\s+([`"\w]+))?'
            r'\s*\(',
            re.IGNORECASE | re.DOTALL,
        )
        hm = header_re.search(ddl)
        if not hm:
            raise ValueError("Not a valid CREATE TABLE statement")

        name = hm.group(1).strip()
        cluster = hm.group(2).strip('`"') if hm.group(2) else None

        # 2. Тело ( ... )
        body_open = ddl.index('(', hm.start())
        body_close = cls._find_closing_paren(ddl, body_open)
        body = ddl[body_open + 1:body_close].strip()
        after_body = ddl[body_close + 1:].strip()

        columns: List[ColumnDef] = []
        indexes: List[IndexDef] = []
        other_body_entries: List[str] = []

        # 3. Парсим строки тела
        for entry in cls._split_top_level_commas(body):
            entry = entry.strip()
            if not entry:
                continue
            up = entry.upper().lstrip()
            if up.startswith('INDEX '):
                indexes.append(cls._parse_index(entry))
            elif up.startswith('PROJECTION ') or up.startswith('CONSTRAINT '):
                other_body_entries.append(entry)
            else:
                columns.append(cls._parse_column(entry))

        obj = cls(
            name=name,
            cluster=cluster,
            columns=columns,
            indexes=indexes,
            other_body_entries=other_body_entries,
        )

        # 4. Опции таблицы после тела
        obj._parse_table_options(after_body)
        return obj

    @classmethod
    def _parse_column(cls, text: str) -> ColumnDef:
        """Парсит одну строку/элемент тела таблицы как колонку."""
        name, rest = cls._consume_identifier(text)
        col_type, rest = cls._consume_type(rest)
        codec, extra = cls._extract_codec(rest)
        return ColumnDef(name=name, type=col_type, codec=codec, extra=extra.strip())

    @classmethod
    def _parse_index(cls, text: str) -> IndexDef:
        """Парсит одну строку/элемент тела таблицы как skip-индекс."""
        raw = text
        rest = re.sub(r'^INDEX\s+', '', text, flags=re.IGNORECASE).lstrip()

        name, rest = cls._consume_identifier(rest)

        # expr — всё до ключевого слова TYPE
        type_m = re.search(r'\bTYPE\s+', rest, re.IGNORECASE)
        if not type_m:
            idx = IndexDef(name=name, expr=rest.strip(), index_type='')
            idx._raw = raw
            return idx

        expr = rest[:type_m.start()].strip()
        rest = rest[type_m.end():]

        idx_type, rest = cls._consume_type(rest)

        gran_m = re.search(r'\bGRANULARITY\s+(\S+)', rest, re.IGNORECASE)
        granularity = gran_m.group(1) if gran_m else None

        idx = IndexDef(name=name, expr=expr, index_type=idx_type,
                granularity=granularity)
        idx._raw = raw
        return idx

    def _parse_table_options(self, text: str) -> None:
        """
        Разбирает текст после тела таблицы на именованные опции.
        Известные: ENGINE, PARTITION BY, ORDER BY, PRIMARY KEY, SAMPLE BY.
        Остальные (TTL, SETTINGS, COMMENT, ...) — в other_table_options.
        """
        clause_re = re.compile(
            r'\b(ENGINE\s*=|PARTITION\s+BY|ORDER\s+BY|PRIMARY\s+KEY'
            r'|SAMPLE\s+BY|TTL\b|SETTINGS\b|COMMENT\b)',
            re.IGNORECASE,
        )
        positions = [
            (m.start(), m.group(0))
            for m in clause_re.finditer(text)
            if self._is_top_level_pos(text, m.start())
        ]
        positions.append((len(text), None))

        for i, (start, kw_raw) in enumerate(positions[:-1]):
            end = positions[i + 1][0]
            chunk = text[start:end].strip().rstrip(';').strip()
            kw = re.sub(r'\s+', ' ', kw_raw).upper().rstrip('= ').strip()

            if kw == 'ENGINE':
                m = re.match(r'ENGINE\s*=\s*(.*)', chunk, re.IGNORECASE | re.DOTALL)
                self.engine = m.group(1).strip() if m else chunk
            elif kw == 'PARTITION BY':
                m = re.match(r'PARTITION\s+BY\s+(.*)', chunk, re.IGNORECASE | re.DOTALL)
                self.partition_by = m.group(1).strip() if m else chunk
            elif kw == 'ORDER BY':
                m = re.match(r'ORDER\s+BY\s+(.*)', chunk, re.IGNORECASE | re.DOTALL)
                self.order_by = m.group(1).strip() if m else chunk
            elif kw == 'PRIMARY KEY':
                m = re.match(r'PRIMARY\s+KEY\s+(.*)', chunk, re.IGNORECASE | re.DOTALL)
                self.primary_key = m.group(1).strip() if m else chunk
            elif kw == 'SAMPLE BY':
                m = re.match(r'SAMPLE\s+BY\s+(.*)', chunk, re.IGNORECASE | re.DOTALL)
                self.sample_by = m.group(1).strip() if m else chunk
            else:
                self.other_table_options.append(chunk)

    # ── сборка DDL ───────────────────────────────────────────────────────────

    def to_ddl(self) -> str:
        """Собирает текущий объект обратно в `CREATE TABLE` SQL."""
        header = f"CREATE TABLE {self.name}"
        if self.cluster:
            header += f" ON CLUSTER {self.cluster}"

        body_lines: List[str] = []
        for col in self.columns:
            body_lines.append(col.to_sql())
        for idx in self.indexes:
            body_lines.append(idx.to_sql())
        for entry in self.other_body_entries:
            body_lines.append("    " + entry)

        body = ',\n'.join(body_lines)
        result = f"{header}\n(\n{body}\n)"

        if self.engine:
            result += f"\nENGINE = {self.engine}"
        if self.partition_by:
            result += f"\nPARTITION BY {self.partition_by}"
        if self.primary_key:
            result += f"\nPRIMARY KEY {self.primary_key}"
        if self.order_by:
            result += f"\nORDER BY {self.order_by}"
        if self.sample_by:
            result += f"\nSAMPLE BY {self.sample_by}"
        for opt in self.other_table_options:
            result += f"\n{opt}"

        return result

    # ── удобные хелперы ──────────────────────────────────────────────────────

    def copy(self) -> 'TableDDL':
        """Глубокая копия — для создания вариантов бенчмарка."""
        return deepcopy(self)

    def column(self, name: str) -> Optional[ColumnDef]:
        """Найти колонку по имени (возвращает живую ссылку — можно мутировать)."""
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def index(self, name: str) -> Optional[IndexDef]:
        """Найти индекс по имени (возвращает живую ссылку — можно мутировать)."""
        for idx in self.indexes:
            if idx.name == name:
                return idx
        return None

    def get_index_granularity(self) -> Optional[int]:
        """
        Возвращает `SETTINGS index_granularity`, если он задан в DDL.

        Ищет ключ в первом `SETTINGS ...` блоке из `other_table_options`.
        """
        for option in self.other_table_options:
            if not re.match(r"^\s*SETTINGS\b", option, flags=re.IGNORECASE):
                continue
            body = re.sub(
                r"^\s*SETTINGS\b",
                "",
                option,
                flags=re.IGNORECASE,
            ).strip()
            for assignment in self._split_top_level_commas(body):
                if re.match(
                    r"^\s*`?index_granularity`?\s*=",
                    assignment,
                    flags=re.IGNORECASE,
                ):
                    _, _, right = assignment.partition("=")
                    raw_value = right.strip().strip("`")
                    try:
                        return int(raw_value)
                    except ValueError:
                        return None
        return None

    def set_index_granularity(self, value: int) -> None:
        """
        Устанавливает `SETTINGS index_granularity = <value>` в DDL.

        Если `SETTINGS` уже есть, обновляет/добавляет ключ внутри него.
        Заодно удаляет дубли `index_granularity` во всех SETTINGS-блоках,
        чтобы в итоговом DDL ключ встречался только один раз.
        Если нет — добавляет новый `SETTINGS`-блок в `other_table_options`.
        """
        if value <= 0:
            raise ValueError("index_granularity должен быть > 0")

        target_assignment = f"index_granularity = {int(value)}"
        settings_indices = [
            idx
            for idx, option in enumerate(self.other_table_options)
            if re.match(r"^\s*SETTINGS\b", option, flags=re.IGNORECASE)
        ]
        if not settings_indices:
            self.other_table_options.append(f"SETTINGS {target_assignment}")
            return

        first_settings_idx = settings_indices[0]
        for idx in settings_indices:
            body = re.sub(
                r"^\s*SETTINGS\b",
                "",
                self.other_table_options[idx],
                flags=re.IGNORECASE,
            ).strip()
            assignments = self._split_top_level_commas(body) if body else []

            normalized_assignments: list[str] = []
            seen_index_granularity = False
            for assignment in assignments:
                if re.match(
                    r"^\s*`?index_granularity`?\s*=",
                    assignment,
                    flags=re.IGNORECASE,
                ):
                    if idx == first_settings_idx and not seen_index_granularity:
                        normalized_assignments.append(target_assignment)
                        seen_index_granularity = True
                    continue
                normalized_assignments.append(assignment.strip())

            if idx == first_settings_idx and not seen_index_granularity:
                normalized_assignments.append(target_assignment)

            if normalized_assignments:
                self.other_table_options[idx] = (
                    "SETTINGS " + ", ".join(normalized_assignments)
                )
            else:
                # Пустой SETTINGS-блок удаляем.
                self.other_table_options[idx] = ""

        self.other_table_options = [
            option for option in self.other_table_options if option.strip()
        ]


# ─── пример использования ────────────────────────────────────────────────────

if __name__ == '__main__':
    SAMPLE_DDL = """
    CREATE TABLE default.events ON CLUSTER my_cluster
    (
        `event_id`   UInt64          CODEC(Delta(8), LZ4),
        `event_time` DateTime        DEFAULT now() CODEC(DoubleDelta, ZSTD(1)),
        `user_id`    UInt32          CODEC(T64, LZ4HC(9)),
        `payload`    Nullable(String),
        `tags`       Array(LowCardinality(String)) COMMENT 'тэги события',
        INDEX idx_user user_id TYPE minmax GRANULARITY 3,
        INDEX idx_payload_bloom payload TYPE bloom_filter(0.01) GRANULARITY 1
    )
    ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/events', '{replica}')
    PARTITION BY toYYYYMM(event_time)
    PRIMARY KEY (user_id, event_id)
    ORDER BY (user_id, event_id, event_time)
    SAMPLE BY user_id
    TTL event_time + INTERVAL 1 YEAR DELETE
    SETTINGS index_granularity = 8192
    """

    table = TableDDL.from_ddl(SAMPLE_DDL)

    print("=== Parsed ===")
    print(f"Table  : {table.name}")
    print(f"Cluster: {table.cluster}")
    print(f"Engine : {table.engine}")
    print(f"Order  : {table.order_by}")
    print(f"PK     : {table.primary_key}")
    print(f"Sample : {table.sample_by}")
    print(f"Other opts: {table.other_table_options}")
    print()
    print("Columns:")
    for col in table.columns:
        print(f"  {col.name}: type={col.type!r}  codec={col.codec!r}  extra={col.extra!r}")
    print()
    print("Indexes:")
    for idx in table.indexes:
        print(f"  {idx.name}: expr={idx.expr!r}  type={idx.index_type!r}  gran={idx.granularity!r}")

    variant = table.copy()
    variant.column('user_id').type = 'UInt16'
    variant.column('user_id').codec = 'CODEC(T64, ZSTD(3))'
    variant.column('event_time').codec = None
    variant.column('payload').type = 'String'
    variant.indexes.append(IndexDef(
        name='idx_tags',
        expr='tags',
        index_type='bloom_filter(0.01)',
        granularity='2',
    ))

    print("\n=== Variant DDL ===")
    print(variant.to_ddl())
