"""Bounded attachment parsing for text, office documents, and images."""

import base64
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile

from docx import Document as WordDocument
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

MAX_CODE_CHARS = 12000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 30

TEXT_UPLOAD_TYPES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".php", ".html", ".css", ".java",
    ".c", ".h", ".cpp", ".cs", ".go", ".rs", ".rb", ".sh", ".sql", ".json",
    ".yaml", ".yml", ".xml", ".txt", ".md", ".rst", ".toml", ".ini", ".cfg",
    ".conf", ".properties", ".gradle", ".csv", ".ipynb",
}

SUPPORTED_UPLOAD_TYPES = [
    "py", "js", "jsx", "ts", "tsx", "php", "html", "css", "java", "c",
    "h", "cpp", "cs", "go", "rs", "rb", "sh", "sql", "json", "yaml",
    "yml", "xml", "txt", "md", "rst", "toml", "ini", "cfg", "conf",
    "properties", "gradle", "dockerfile", "ipynb", "csv", "pdf", "docx",
    "png", "jpg", "jpeg", "webp", "gif",
]


def safe_filename(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:100] or "uploaded file"


def process_uploads(uploaded_files) -> tuple[str, list[dict[str, str]], list[str]]:
    """Extract bounded text and normalized image data from chat attachments."""
    extracted_text = []
    images = []
    names = []
    total_bytes = 0
    total_text_chars = 0

    for uploaded in uploaded_files:
        filename = safe_filename(uploaded.name)
        data = uploaded.getvalue()
        total_bytes += len(data)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"{filename} exceeds the 8 MiB per-file limit.")
        if total_bytes > 20 * 1024 * 1024:
            raise ValueError("Attachments in one message may total at most 20 MiB.")

        extension = Path(filename.lower()).suffix
        names.append(filename)
        if extension in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            try:
                with Image.open(BytesIO(data)) as original:
                    if original.width * original.height > 20_000_000:
                        raise ValueError(f"{filename} is too large to safely process.")
                    image = original.convert("RGB")
                    image.thumbnail((1600, 1600))
                    output = BytesIO()
                    image.save(output, format="JPEG", optimize=True, quality=85)
            except (
                Image.DecompressionBombError,
                UnidentifiedImageError,
                OSError,
            ) as error:
                raise ValueError(f"{filename} is not a readable image.") from error
            images.append(
                {
                    "name": filename,
                    "mime": "image/jpeg",
                    "data": base64.b64encode(output.getvalue()).decode("ascii"),
                }
            )
            continue

        if extension == ".pdf":
            reader = PdfReader(BytesIO(data), strict=False)
            page_text = [
                page.extract_text() or ""
                for page in reader.pages[:MAX_PDF_PAGES]
            ]
            text = "\n\n".join(page_text)
            if len(reader.pages) > MAX_PDF_PAGES:
                text += f"\n[Only the first {MAX_PDF_PAGES} PDF pages were included.]"
        elif extension == ".docx":
            with ZipFile(BytesIO(data)) as archive:
                expanded_size = sum(item.file_size for item in archive.infolist())
                if expanded_size > 40 * 1024 * 1024:
                    raise ValueError(
                        f"{filename} expands beyond the 40 MiB safety limit."
                    )
            document = WordDocument(BytesIO(data))
            text = "\n".join(
                item.text for item in document.paragraphs if item.text.strip()
            )
            table_text = [
                " | ".join(cell.text for cell in row.cells)
                for table in document.tables
                for row in table.rows
            ]
            if table_text:
                text += "\n\n" + "\n".join(table_text)
        elif extension in TEXT_UPLOAD_TYPES or filename.lower() in {
            "dockerfile",
            "makefile",
        }:
            text = data.decode("utf-8-sig", errors="replace")
        else:
            raise ValueError(
                f"{filename} is not a supported text, source, PDF, DOCX, or image file."
            )

        remaining = MAX_CODE_CHARS - total_text_chars
        if remaining <= 0:
            extracted_text.append("[Further files omitted: message text limit reached.]")
            break
        if len(text) > remaining:
            text = text[:remaining] + "\n[File content truncated at the message limit.]"
        total_text_chars += len(text)
        extracted_text.append(f"--- File: {filename} ---\n{text}")

    return "\n\n".join(extracted_text), images, names
