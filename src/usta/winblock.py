"""Windows'un uygulama denetimi imzasız bir parçayı engellediğinde Python dökümü yerine düz Türkçe açıklama.

Windows 11'in Akıllı Uygulama Denetimi (temiz kurulumda açık gelir) pip ile kurulan imzasız derlenmiş parçaları
(`.pyd`) yüklemez; Usta daha kendi koduna gelmeden düşer. Bu modül yalnız standart kitaplığı kullanır.
"""

from __future__ import annotations

import re
import sys

# hata metni Windows'un dilinde gelir; bilinen iki dil ve genel "policy/ilke" sözcüğü
_POLICY = re.compile(r"Application Control|Uygulama Denetimi|policy|ilkesi", re.IGNORECASE)

MESSAGE = (
    "Usta açılamadı: Windows'un Akıllı Uygulama Denetimi, Usta'nın kullandığı bir parçayı ({part}) imzasız olduğu "
    "için engelledi.\n\n"
    "Bu bir arıza değil, bilgisayarının koruması; kapatma (kapatınca geri açmak için Windows'u sıfırlamak "
    "gerekebilir).\n\n"
    "Usta'nın imzalı Windows sürümü hazırlanıyor. O zamana kadar Usta bu bilgisayarda çalışamaz.\n"
    "Ayrıntı: https://github.com/SoundByGAIA/usta/blob/main/docs/baslangic.md"
)


def explain(err: BaseException) -> str | None:
    text = str(err)
    if "DLL load failed" not in text or not _POLICY.search(text):
        return None
    m = re.search(r"importing (\w+)", text)
    return MESSAGE.format(part=m.group(1) if m else "bir parça")


def show(message: str) -> None:
    """Konsol varsa yazar; masaüstü simgesinden (pythonw, konsolsuz) açıldıysa pencerede gösterir."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
        return
    import ctypes  # Python'un kendi parçası, imzalıdır

    ctypes.windll.user32.MessageBoxW(None, message, "Usta", 0x10)
