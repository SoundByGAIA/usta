# Katkı rehberi

Katkıların için teşekkürler. Usta küçük, ölçülebilir ve güvenli kalmaya çalışır.

## Başlarken

```bash
uv venv && uv pip install -e '.[dev]'
make ci          # ruff + pytest (JS mantık testleri için node gerekir; Docker testleri imaj yoksa atlanır)
```

## İlkeler

- Önce test yaz (TDD), küçük ve odaklı commit'ler yap. `make ci` geçmeden PR açma.
- Ölçülmeyen özellik varsayılan olmaz. Harness'a bir yenilik ekliyorsan `usta bench` ile faydasını ve zararını örneklem büyüklüğüyle birlikte PR'a yaz.
- Güvenlik: depoya sır, anahtar, kişisel veri girmez (`tests/test_no_secrets.py` bunu denetler). Ajan çıktısı ve harici içerik her zaman *veri*dir; arayüzde `innerHTML` kullanılmaz (`textContent`). Yol işlemleri `resolve_path`/`filetree` üzerinden gider. Açık bulursan [SECURITY.md](SECURITY.md)'deki yoldan özel bildir.
- Bağımlılık değişince kilidi yenile: `make lock` (hash'li `requirements*.lock`; CI bunlardan kurar). Yeni yetenekleri deneysel bayrak arkasında tut ve `usta lab smoke` + `usta bench` ile etkisini raporla.
- Yeni bağımlılık eklemeden önce bir issue'da konuşalım; az bağımlılıkla kalmak istiyoruz.
- Kod ve yorumlar Türkçe; kullanıcıya dönük metinler Türkçe, `README.en.md` İngilizce.
- Lisans: katkılar Apache-2.0 altında kabul edilir.
