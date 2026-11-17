# Ayarlar

Usta'nın ortam değişkenleri ve davranışı değiştiren komut satırı seçenekleri. Arayüzdeki ayarlar burada yok; onlar
panelin Ayarlar bölümünde anlatılıyor.

Yeni bir ayar eklendiğinde bu listeye girer. Deneysel bir ayar ölçülüp karara bağlanınca ya varsayılan olur ya da
kaldırılır.

## Model ve bağlantı

| Ayar | Ne yapar | Varsayılan |
|---|---|---|
| `USTA_ENDPOINT`, `--endpoint` | OpenAI-uyumlu uç nokta | `http://127.0.0.1:11434/v1` (Ollama) |
| `USTA_MODEL`, `--model` | model adı | ilk açılışta seçilir |
| `USTA_API_KEY` | komut satırında kullanılan anahtar (panelde bağlanan API'ler bunu görmez) | yok |
| `USTA_PROTOCOL`, `--protocol` | araç çağrısı biçimi: `native`, `json`, `text`, `auto` | `native` |
| `--think` | düşünme ayarı (`reasoning_effort` olarak gider): `auto`, `off`, `low`, `medium`, `high` | `auto` (modelin kendi ayarı) |
| `--extra-body` | isteğe eklenecek JSON alanları | yok |
| `--model-timeout` | tek model isteği için bekleme süresi (saniye) | 120 |
| `--context-window` | bağlam penceresi (token); kısaltma eşiği buna göre ayarlanır | modelden |

## Güvenlik

| Ayar | Ne yapar | Varsayılan |
|---|---|---|
| `USTA_ALLOW_HOSTS`, `--allow-host` | kutunun ağdan erişebileceği alan adları | ağ kapalı |
| `USTA_TAINT_GATE=0`, `--no-taint-gate` | kaynak izi kapısını kapatır | açık |
| `USTA_HOME` | Usta'nın ayar ve kayıt klasörü | `~/.usta` |
| `--mode` | `manuel`, `oto`, `plan` | `manuel` |
| `--lan` | paneli evdeki ağa PIN'le açar | kapalı |

`USTA_ALLOW_PRIVATE`, `USTA_PORTS` ve `USTA_DELEGATED` Usta'nın kendi iç kullanımı içindir (kutudaki proxy'ye ve
çağrılan programlara verilir); elle ayarlanmaz.

## Küçük model yardımcıları

| Ayar | Ne yapar | Varsayılan | Durum |
|---|---|---|---|
| `USTA_FINISH_CHECK=0`, `--no-finish-check` | söz–eylem denetimini kapatır | açık | ölçüldü: [olcumler/soz-eylem.md](olcumler/soz-eylem.md) |
| `--guard` | doğrulama kapısı ve devre kesici | kapalı | zayıf modelde tek başına fayda göstermedi: [arsiv/0.2.0-olcumleri.md](arsiv/0.2.0-olcumleri.md) |
| `USTA_SITE_STEPS=1` | yeni site isteğini parça parça kurar | kapalı | deneysel; ölçüm: [olcumler/site-istekleri.md](olcumler/site-istekleri.md) |
| `USTA_SITE_LEVEL=1\|2\|3` | parça büyüklüğü (1 en küçük); verilmezse beceri sondası seçer | sonda | deneysel; sonda henüz kararlı değil |
| `USTA_WORKSPACE_HINT=1` | görev başında klasördeki dosya adlarını modele söyler | kapalı | deneysel, ölçülmedi |
| `USTA_SYMBOL_TOOLS=1`, `--symbol-tools` | Tree-sitter sembol araçları (`pip install 'usta[symbols]'`) | kapalı | deneysel |

## Ölçüm araçları

`usta lab run` ve `usta bench run` yukarıdaki model seçeneklerini alır. Bunlara özgü olanlar:

| Seçenek | Ne yapar |
|---|---|
| `--strong-model`, `--strong-endpoint`, `--strong-protocol`, `--strong-api-key-env` | kademeli yönlendirme: takılınca aynı konuşmayı güçlü modelle sürdürür (deneysel, yalnız ölçümde; [olcumler/kademeli-yonlendirme.md](olcumler/kademeli-yonlendirme.md)) |
| `--repeat`, `--scenario`, `--category` | Lab'da tekrar sayısı ve senaryo seçimi |
| `--breaker` | Lab'da devre kesici |
| `--shrink-writes` | bench'te eski yazmaların gövdesini bağlamdan atar (deneysel, fayda göstermedi) |
