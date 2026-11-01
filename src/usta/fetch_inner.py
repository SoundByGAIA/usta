"""Sandbox konteynerinde çalışır (yalnız stdlib): tek URL'yi GET'ler, sınırlı okur, JSON basar.

argv: URL MAX_BAYT ZAMAN_AŞIMI_SN [PDF_MAX_BAYT ÇIKTI_DİZİNİ]. PDF gövdesi stdout'a değil
ÇIKTI_DİZİNİ/body.pdf dosyasına yazılır; PDF kırpılırsa kullanılamaz, bu yüzden hata sayılır. Ağ çıkışı yalnız ortamdaki allowlist proxy'den geçer.
Sıkıştırılmış içerik, http/https dışı yönlendirme ve süre aşımı hata olarak döner.
"""

import base64
import json
import os
import sys
import time
import urllib.request
from urllib.error import HTTPError

CHUNK = 65_536


def emit(**kw):
    data = {
        "status": None,
        "url": None,
        "ctype": "",
        "charset": None,
        "truncated": False,
        "error": None,
        "body_b64": "",
        "body_file": None,
    }
    data.update(kw)
    print(json.dumps(data))
    sys.exit(0)


def main():
    url, max_bytes, timeout = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
    pdf_max = int(sys.argv[4]) if len(sys.argv) > 4 else max_bytes
    outdir = sys.argv[5] if len(sys.argv) > 5 else "/workspace"
    if not url.lower().startswith(("http://", "https://")):
        emit(url=url, error="yalnız http/https desteklenir")
    deadline = time.monotonic() + timeout
    opener = urllib.request.OpenerDirector()  # FTP/file işleyicileri bilerek yok
    for h in (
        urllib.request.ProxyHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPRedirectHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(h)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "usta-fetch/0.3",
            "Accept-Encoding": "identity",
            "Accept": "text/html,text/plain,application/pdf,application/json;q=0.9,*/*;q=0.1",
        },
    )
    try:
        resp = opener.open(req, timeout=timeout)
        final = resp.geturl()
        enc = (resp.headers.get("Content-Encoding") or "identity").strip().lower()
        if enc not in ("", "identity"):
            emit(status=resp.status, url=final, error="sıkıştırılmış içerik desteklenmiyor")
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        charset = resp.headers.get_content_charset()
        is_pdf = ctype == "application/pdf"
        if is_pdf:
            max_bytes = pdf_max
        body = b""
        while len(body) <= max_bytes:
            if time.monotonic() > deadline:
                emit(status=resp.status, url=final, error="zaman aşımı (toplam süre)")
            chunk = resp.read1(
                min(CHUNK, max_bytes + 1 - len(body))
            )  # read(n) tamponu doldurana dek bekler
            if not chunk:
                break
            body += chunk
        truncated = len(body) > max_bytes
        if is_pdf:
            if truncated:
                emit(
                    status=resp.status,
                    url=final,
                    ctype=ctype,
                    error=f"PDF {max_bytes} bayttan büyük",
                )
            fd = os.open(
                os.path.join(outdir, "body.pdf"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(fd, "wb") as f:
                f.write(body)
            emit(status=resp.status, url=final, ctype=ctype, body_file="body.pdf")
        emit(
            status=resp.status,
            url=final,
            ctype=ctype,
            charset=charset,
            truncated=truncated,
            body_b64=base64.b64encode(body[:max_bytes]).decode(),
        )
    except HTTPError as e:
        emit(status=e.code, url=e.url, error=f"HTTP {e.code}")
    except TimeoutError:
        emit(url=url, error="zaman aşımı")
    except Exception as e:  # noqa: BLE001 - ağ/SSL/URL hataları modele kısa metin olarak döner
        emit(url=url, error=f"{type(e).__name__}: {str(getattr(e, 'reason', e))[:150]}")


main()
