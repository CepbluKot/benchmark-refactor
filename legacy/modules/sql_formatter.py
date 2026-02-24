import re


def find_matching_paren(s, start_idx):
    """Находит индекс закрывающей скобки, соответствующей открывающей в start_idx.
    Учитывает кавычки, обратные кавычки и комментарии."""
    depth = 0
    in_single = in_double = in_backtick = in_brackets = False
    in_line_comment = in_block_comment = False
    i = start_idx
    while i < len(s):
        c = s[i]
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
        elif in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 1
        elif c == "-" and nxt == "-":
            in_line_comment = True
            i += 1
        elif c == "/" and nxt == "*":
            in_block_comment = True
            i += 1
        elif c == "'" and not in_double and not in_backtick:
            in_single = not in_single
        elif c == '"' and not in_single and not in_backtick:
            in_double = not in_double
        elif c == "`" and not in_single and not in_double:
            in_backtick = not in_backtick
        elif c == "[" and not in_single and not in_double and not in_backtick:
            in_brackets = True
        elif c == "]" and in_brackets:
            in_brackets = False
        elif not (in_single or in_double or in_backtick or in_brackets or in_line_comment or in_block_comment):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def split_top_level_commas(s):
    """Split string by commas that are top-level (not inside (), quotes, backticks, comments)."""
    parts = []
    buf = []
    depth = 0
    in_single = in_double = in_backtick = in_brackets = False
    in_line_comment = in_block_comment = False
    i = 0
    while i < len(s):
        c = s[i]
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if in_line_comment:
            buf.append(c)
            if c == "\n":
                in_line_comment = False
        elif in_block_comment:
            buf.append(c)
            if c == "*" and nxt == "/":
                buf.append(nxt)
                i += 1
                in_block_comment = False
        elif c == "-" and nxt == "-":
            buf.append(c)
            buf.append(nxt)
            i += 1
            in_line_comment = True
        elif c == "/" and nxt == "*":
            buf.append(c)
            buf.append(nxt)
            i += 1
            in_block_comment = True
        elif c == "'" and not in_double and not in_backtick:
            in_single = not in_single
            buf.append(c)
        elif c == '"' and not in_single and not in_backtick:
            in_double = not in_double
            buf.append(c)
        elif c == "`" and not in_single and not in_double:
            in_backtick = not in_backtick
            buf.append(c)
        elif c == "[" and not in_single and not in_double and not in_backtick:
            in_brackets = True
            buf.append(c)
        elif c == "]" and in_brackets:
            in_brackets = False
            buf.append(c)
        else:
            if not (in_single or in_double or in_backtick or in_brackets or in_line_comment or in_block_comment):
                if c == "(":
                    depth += 1
                elif c == ")":
                    if depth > 0:
                        depth -= 1
                if c == "," and depth == 0:
                    parts.append("".join(buf).strip())
                    buf = []
                    i += 1
                    continue
            buf.append(c)
        i += 1
    last = "".join(buf).strip()
    if last:
        parts.append(last)
    return parts


def format_create_table(ddl: str, indent: str = "    ") -> str:
    """Форматирует CREATE TABLE, возвращает многострочный ddl-представление."""
    if not isinstance(ddl, str):
        ddl = ddl.decode("utf-8", errors="replace")
    s = " ".join(ddl.strip().split())
    m = re.search(r"\(", s)
    if not m:
        return ddl
    start = m.start()
    end = find_matching_paren(s, start)
    if end == -1:
        return ddl
    header = s[:start].strip()
    inner = s[start + 1:end].strip()
    footer = s[end + 1:].strip()
    columns = split_top_level_commas(inner)
    cols_formatted = ",\n".join(indent + col.strip() for col in columns if col.strip())
    result = f"{header} (\n{cols_formatted}\n)"
    if footer:
        result += " " + footer
    if ddl.strip().endswith(";") and not result.strip().endswith(";"):
        result = result.rstrip() + ";"
    return result