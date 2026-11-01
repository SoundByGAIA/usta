"""Sandbox konteynerinde çalışır (ağsız): PDF'ten metin çıkarır, JSON basar.

argv: PDF_YOLU MAKS_SAYFA MAKS_KARAKTER. pypdf ana makineden salt okunur bağlanır
(/opt/pylib); güvenilmeyen PDF ayrıştırması bu yüzden ana süreçte değil burada yapılır.
"""

import json
import sys

sys.path.insert(0, "/opt/pylib")


def emit(**kw):
    data = {
        "error": None,
        "total_pages": 0,
        "read_pages": 0,
        "pages": [],
        "truncated": False,
        "empty": False,
    }
    data.update(kw)
    print(json.dumps(data))
    sys.exit(0)


def main():
    path, max_pages, max_chars = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    try:
        from pypdf import PdfReader

        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            emit(error="şifreli PDF desteklenmiyor")
        total = len(reader.pages)
        pages, used, truncated = [], 0, False
        for page in reader.pages[:max_pages]:
            text = page.extract_text() or ""
            room = max_chars - used
            if len(text) > room:
                text, truncated = text[: max(room, 0)], True
            pages.append(text)
            used += len(text)
            if truncated:
                break
        emit(
            total_pages=total,
            read_pages=len(pages),
            pages=pages,
            truncated=truncated,
            empty=not any(p.strip() for p in pages),
        )
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - bozuk PDF ayrıştırıcıyı düşürse bile kısa hata döner
        emit(error=f"PDF okunamadı: {type(e).__name__}: {str(e)[:120]}")


main()
