from __future__ import annotations

from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 12000
MAX_PDF_PAGES = 25
MAX_IMAGE_PIXELS = 12_000_000
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".py", ".log", ".html", ".xml"}


def extract_text(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    try:
        if not p.is_file() or p.stat().st_size > MAX_BYTES:
            return {"ok": False, "error": "file_missing_or_too_large"}
    except OSError:
        return {"ok": False, "error": "file_unavailable"}

    suffix = p.suffix.lower()
    try:
        if suffix in TEXT_EXTS:
            return {"ok": True, "text": p.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS], "type": suffix}

        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return {"ok": False, "error": "pypdf_not_installed"}
            reader = PdfReader(str(p))
            if len(reader.pages) > MAX_PDF_PAGES:
                return {"ok": False, "error": "pdf_too_many_pages"}
            chunks: list[str] = []
            remaining = MAX_TEXT_CHARS
            for page in reader.pages:
                if remaining <= 0:
                    break
                page_text = page.extract_text() or ""
                chunks.append(page_text[:remaining])
                remaining -= len(chunks[-1])
            return {"ok": True, "text": "\n".join(chunks)[:MAX_TEXT_CHARS], "type": "pdf"}

        if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            try:
                import pytesseract
                from PIL import Image
            except ImportError:
                return {"ok": False, "error": "ocr_dependencies_not_installed"}
            with Image.open(p) as image:
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS:
                    return {"ok": False, "error": "image_too_large"}
                image.load()
                text = pytesseract.image_to_string(image)
            return {"ok": True, "text": text[:MAX_TEXT_CHARS], "type": "ocr"}

        return {"ok": False, "error": "unsupported_file_type"}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
