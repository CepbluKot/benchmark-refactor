import logging
from typing import Dict, List, Tuple

from clickhouse_connect.driver.client import Client
from modules.interfaces import DatabaseCol

logger = logging.getLogger(__name__)

identifiers_to_ignore = [
    "PRIMARY KEY", "UNIQUE", "NOT NULL", "FOREIGN KEY", "CHECK", "CONSTRAINT",
    "DEFAULT", "INDEX", "UNIQUE KEY", "FULLTEXT INDEX", "SPATIAL INDEX",
    "ARRAY", "TUPLE", "JSON", "MAP", "UUID", "BLOB", "DECIMAL",
    "INT", "BIGINT", "SMALLINT", "VARCHAR", "CHAR", "TEXT",
    "DATE", "TIME", "TIMESTAMP", "SERIAL", "CODEC", "ALIAS", "GENERATED", "COMMENT",
]


def split_sql_ddl_row(text):
    result = []
    current_elem = ""
    depth = 0
    in_quote = False
    quote_char = None
    for char in text:
        if char in ("'", '"'):
            if not in_quote:
                in_quote = True
                quote_char = char
            elif char == quote_char:
                in_quote = False
                quote_char = None
        if not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
        if char == " " and depth == 0 and not in_quote:
            if current_elem:
                result.append(current_elem)
                current_elem = ""
        else:
            current_elem += char
    if current_elem:
        result.append(current_elem)
    return result


def remove_sql_comments_preserve_positions(s: str) -> str:
    n = len(s)
    out = list(s)
    i = 0
    quote = None
    while i < n:
        ch = s[i]
        if quote is not None:
            if quote == "[":
                if ch == "]":
                    quote = None
            else:
                if ch == quote:
                    quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue
        if ch == "[":
            quote = "["
            i += 1
            continue
        if s.startswith("/*", i):
            j = s.find("*/", i + 2)
            end = (j + 2) if j != -1 else n
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        if s.startswith("--", i):
            j = s.find("\n", i + 2)
            end = j if j != -1 else n
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        if ch == "#":
            j = s.find("\n", i + 1)
            end = j if j != -1 else n
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def split_between_parens(s: str, open_idx: int, close_idx: int) -> List[str]:
    if not (0 <= open_idx < len(s) and 0 <= close_idx <= len(s) and open_idx < close_idx):
        raise ValueError("Неверные open_idx/close_idx")
    if s[open_idx] != "(" or s[close_idx] != ")":
        raise ValueError("open_idx/close_idx не указывают на '(' и ')'")
    inner = s[open_idx + 1:close_idx]
    parts: List[str] = []
    i = 0
    n = len(inner)
    buf_start = 0
    paren = 0
    in_s = in_d = in_bt = in_br = False
    while i < n:
        ch = inner[i]
        if ch == "'" and not (in_d or in_bt or in_br):
            in_s = not in_s
            i += 1
            continue
        if ch == '"' and not (in_s or in_bt or in_br):
            in_d = not in_d
            i += 1
            continue
        if ch == "`" and not (in_s or in_d or in_br):
            in_bt = not in_bt
            i += 1
            continue
        if ch == "[" and not (in_s or in_d or in_bt):
            in_br = True
            i += 1
            continue
        if ch == "]" and in_br:
            in_br = False
            i += 1
            continue
        if in_s or in_d or in_bt or in_br:
            i += 1
            continue
        if ch == "(":
            paren += 1
            i += 1
            continue
        if ch == ")":
            if paren > 0:
                paren -= 1
            i += 1
            continue
        if ch == "," and paren == 0:
            part_text = inner[buf_start:i].strip()
            if part_text:
                parts.append(part_text)
            buf_start = i + 1
            i += 1
            continue
        i += 1
    tail = inner[buf_start:n].strip()
    if tail:
        parts.append(tail)
    return parts


def find_all_bracket_pairs(s: str) -> Tuple[List[int], Dict[int, int], Dict[int, int]]:
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = {v: k for k, v in pairs.items()}
    n = len(s)
    matches: List[int] = [-1] * n
    stack: List[int] = []
    for i, ch in enumerate(s):
        if ch in pairs:
            stack.append(i)
        elif ch in closing:
            if stack and s[stack[-1]] == closing[ch]:
                open_idx = stack.pop()
                matches[open_idx] = i
                matches[i] = open_idx
    open_to_close = {i: matches[i] for i in range(n) if matches[i] != -1 and s[i] in pairs}
    close_to_open = {i: matches[i] for i in range(n) if matches[i] != -1 and s[i] in closing}
    return matches, open_to_close, close_to_open


def get_splitted_table(db_client: Client, db_name: str, table_name: str) -> List[str]:
    try:
        res = db_client.command(f"show create table {db_name}.{table_name};")
        if isinstance(res, str):
            res_w_removed_comments = remove_sql_comments_preserve_positions(res)
            res_cleaned = (
                res_w_removed_comments.replace("\\n", " ").replace("\n", "").replace("\\", "")
            )
            res_cleaned = " ".join(res_cleaned.split())
            _, bracket_open_2_close, _ = find_all_bracket_pairs(res_cleaned)
            create_table_open_bracket_id = res_cleaned.find("(")
            create_table_close_bracket_id = bracket_open_2_close.get(create_table_open_bracket_id)
            if not create_table_close_bracket_id:
                raise Exception(f"Cant parse DDL str: {res_cleaned}")
            items = split_between_parens(
                res_cleaned, create_table_open_bracket_id, create_table_close_bracket_id
            )
            return (
                [res_cleaned[:create_table_open_bracket_id + 1]]
                + items
                + [res_cleaned[create_table_close_bracket_id:]]
            )
        return []
    except Exception as e:
        logger.error(f"Error occupied while splitting the table {db_name}.{table_name}: {e}")
        return []


def parse_table_cols(splitted_table: List[str]) -> Tuple[DatabaseCol]:
    parsed_cols = []
    for row_id in range(1, len(splitted_table) - 1):
        row_to_parse = splitted_table[row_id]
        elems_of_row = split_sql_ddl_row(row_to_parse)
        if (
            not elems_of_row
            or elems_of_row[0].upper() in identifiers_to_ignore
            or len(elems_of_row) < 2
        ):
            parsed_cols.append(
                DatabaseCol(name="", datatype="", codec="", other_params=row_to_parse)
            )
            continue
        col_name = elems_of_row[0]
        datatype = elems_of_row[1]
        codec = ""
        codec_elem_id = -1
        for id, elem in enumerate(elems_of_row):
            if "CODEC" in elem.upper():
                codec = elem
                codec_elem_id = id
                break
        elems_of_row[0] = ""
        elems_of_row[1] = ""
        if codec_elem_id != -1:
            elems_of_row[codec_elem_id] = ""
        other_params = " ".join(elems_of_row).strip()
        parsed_cols.append(
            DatabaseCol(
                name=col_name.replace("`", ""),
                datatype=datatype,
                codec=codec,
                other_params=other_params,
            )
        )
    return tuple(parsed_cols)