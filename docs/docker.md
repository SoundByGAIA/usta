# Usta'yı Docker ile sunucuda çalıştırmak

Usta'yı kendi bilgisayarında açmak için bu sayfaya gerek yok ([baslangic.md](baslangic.md)). Bu yol, Usta'yı bir ev
sunucusunda ya da güçlü bir makinede (ör. modellerin çalıştığı bir GPU sunucusu) sürekli açık bir servis olarak
çalıştırmak isteyenler içindir.

## Başlatma

```bash
git clone https://github.com/SoundByGAIA/usta && cd usta
cp .env.ornek .env        # USTA_MODEL ve gerekirse USTA_ENDPOINT, USTA_API_KEY yaz
docker compose up -d --build
docker compose exec usta cat /data/token   # panele girerken istenen jeton
```

Panel: `http://127.0.0.1:8765`. Jetonu panelin istediği kutuya yapıştır.

## Ayarlar (.env)

| Ad | Ne işe yarar |
|---|---|
| `USTA_MODEL` | Model adı (zorunlu) |
| `USTA_ENDPOINT` | OpenAI uyumlu model adresi. Varsayılan: aynı makinedeki Ollama |
| `USTA_API_KEY` | Bulut servisinin anahtarı (Ollama'da boş) |
| `USTA_BIND` | `127.0.0.1` yalnız bu makine; `0.0.0.0` ev ağındaki cihazlar da açar |
| `USTA_PORT` | Panelin portu (varsayılan 8765) |

Ayarlar, jeton, işler ve denetim kaydı `usta-veri` biriminde durur; konteyner silinse de kalır.

## Bilinmesi gerekenler

- **Aynı makinedeki Ollama:** Ollama varsayılan olarak yalnız `127.0.0.1`'de dinler, konteyner ona ulaşamaz. Ollama'yı
  `OLLAMA_HOST=0.0.0.0` ile başlat ya da `USTA_ENDPOINT`'e modelin ağ adresini yaz.
- **Komut çalıştırma kapalı:** Usta komutları Docker kutusunda çalıştırır; konteynerin içinde Docker yoktur, bu yüzden
  `run` aracı çalışmaz. Dosya okuma, yazma ve düzenleme çalışır (sayfa, belge, uygulama yapmak için yeterli). Docker
  soketini konteynere bağlamak konteynere ana makinede tam yetki verir; bu yüzden hazır ayarda yoktur.
- **Ev ağına açmak:** `USTA_BIND=0.0.0.0` trafiği şifrelemez. Yalnız güvendiğin ağda kullan; internete açacaksan önüne
  HTTPS veren bir ters vekil koy.
