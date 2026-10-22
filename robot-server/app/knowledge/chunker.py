from pathlib import Path


CODE_EXTENSIONS = {
    ".py",
    ".h",
    ".hpp",
    ".c",
    ".cc",
    ".cpp",
    ".sh",
    ".bash",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".yaml",
    ".yml",
    ".json",
    ".xml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".msg",
}


SPECIAL_CODE_FILENAMES = {
    "dockerfile",
    "makefile",
}


def chunk_text(
    text,
    chunk_size=1200,
    overlap=200,
):

    text = text.strip()

    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):

        end = min(
            len(text),
            start + chunk_size,
        )

        if end < len(text):

            break_position = text.rfind(
                "\n",
                start,
                end,
            )

            if break_position <= start:

                break_position = text.rfind(
                    " ",
                    start,
                    end,
                )

            if (
                break_position
                > start + chunk_size // 2
            ):
                end = break_position

        chunk = text[
            start:end
        ].strip()

        if chunk:

            chunks.append({
                "text": chunk,
                "start_line": None,
                "end_line": None,
            })

        if end >= len(text):
            break

        start = max(
            end - overlap,
            start + 1,
        )

    return chunks


def chunk_code(
    text,
    chunk_size=1600,
    overlap_lines=8,
):
    """
    Código/config é quebrado preservando
    linhas inteiras.

    Isso evita cortar funções, structs e
    blocos YAML no meio de uma linha.
    """

    lines = text.splitlines()

    if not lines:
        return []

    chunks = []

    start_line = 0

    while start_line < len(lines):

        current = []

        current_size = 0

        end_line = start_line

        while end_line < len(lines):

            line = lines[end_line]

            added = len(line) + 1

            if (
                current
                and current_size + added
                > chunk_size
            ):
                break

            current.append(line)

            current_size += added

            end_line += 1

        if not current:

            current = [
                lines[start_line]
            ]

            end_line = start_line + 1

        value = "\n".join(
            current
        ).strip()

        if value:

            chunks.append({
                "text": value,

                "start_line":
                    start_line + 1,

                "end_line":
                    end_line,
            })

        if end_line >= len(lines):
            break

        start_line = max(
            start_line + 1,
            end_line - overlap_lines,
        )

    return chunks


def chunk_document(
    path: Path,
    text,
    chunk_size=1200,
    overlap=200,
):

    name = path.name.lower()

    extension = (
        path.suffix.lower()
    )

    is_code = (
        extension in CODE_EXTENSIONS

        or name
        in SPECIAL_CODE_FILENAMES

        or name.startswith(
            "dockerfile__"
        )
    )

    if is_code:

        return chunk_code(
            text,

            chunk_size=max(
                chunk_size,
                1600,
            ),

            overlap_lines=8,
        )

    return chunk_text(
        text,
        chunk_size=chunk_size,
        overlap=overlap,
    )
