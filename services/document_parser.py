from __future__ import annotations

from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".py", ".log", ".html", ".xml"}


def extract_text(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.is_file() or p.stat().st_size > MAX_BYTES:
        return {"ok": False, "error": "file_missing_or_too_large"}
    suffix = p.suffix.lower()
    try:
        if suffix in TEXT_EXTS:
            return {"ok": True, "text": p.read_text(encoding="utf-8", errors="replace")[:20000], "type": suffix}
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return {"ok": False, "error": "pypdf_not_installed"}
            text = "\n".join((page.extract_text() or "") for page in PdfReader(str(p)).pages)
            return {"ok": True, "text": text[:20000], "type": "pdf"}
        if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            try:
                import pytesseract
                from PIL import Image
            except ImportError:
                return {"ok": False, "error": "ocr_dependencies_not_installed"}
            return {"ok": True, "text": pytesseract.image_to_string(Image.open(p))[:20000], "type": "ocr"}
        return {"ok": False, "error": "unsupported_file_type"}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
