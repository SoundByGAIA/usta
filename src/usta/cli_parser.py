"""Komut satırı: alt komutlar ve seçenekler (argparse)."""

from __future__ import annotations

import argparse

from usta import bench, cli, cli_audit, mcpconfig, thinking


def add_strong_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--strong-model",
        help="kademeli yönlendirme: takılınca devredilecek güçlü model (--model ucuz model olur)",
    )
    p.add_argument(
        "--strong-endpoint", help="güçlü modelin uç noktası (verilmezse --endpoint ile aynı)"
    )
    p.add_argument(
        "--strong-protocol",
        choices=cli.PROTOCOLS,
        help="güçlü modelin araç protokolü (verilmezse --protocol ile aynı)",
    )
    p.add_argument(
        "--strong-api-key-env",
        metavar="ORTAM_DEĞİŞKENİ",
        help="güçlü model için anahtarın okunacağı ortam değişkeni (verilmezse USTA_API_KEY)",
    )


def add_model_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--endpoint",
        help=f"OpenAI-uyumlu uç nokta (USTA_ENDPOINT; varsayılan {cli.DEFAULT_ENDPOINT})",
    )
    p.add_argument("--model", help="model adı (USTA_MODEL)")
    p.add_argument(
        "--extra-body",
        help='isteğe eklenecek JSON alanları, ör. \'{"chat_template_kwargs": {"enable_thinking": false}}\'',
    )
    p.add_argument(
        "--think",
        choices=thinking.THINK,
        help="düşünme ayarı (reasoning_effort olarak gönderilir; off: kapalı). Varsayılan: modelin kendi ayarı",
    )
    p.add_argument(
        "--model-timeout",
        type=float,
        default=120.0,
        help="tek model isteği için saniye (yavaş yerel modellerde artır)",
    )
    p.add_argument(
        "--allow-host",
        action="append",
        help="sandbox'ın proxy ile erişebileceği alan adı; tekrarlanabilir, *.örnek.com olabilir "
        "(USTA_ALLOW_HOSTS, virgüllü). Varsayılan: ağ kapalı",
    )
    p.add_argument(
        "--symbol-tools",
        action="store_true",
        help="DENEYSEL: find_symbol/symbol_context/related_files araçlarını aç (pip install 'usta[symbols]'; USTA_SYMBOL_TOOLS=1)",
    )
    p.add_argument(
        "--taint-gate",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="kaynak izi kapısı (varsayılan AÇIK): okunan içerikten türeyen yazma/komut hedefleri onay ister, "
        "oto modda reddedilir; kapatmak için --no-taint-gate ya da USTA_TAINT_GATE=0",
    )
    p.add_argument(
        "--finish-check",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="söz–eylem denetimi (varsayılan AÇIK): istenen dosyayı yazmadan bitirmek isteyen modele kısa hatırlatma; "
        "kapatmak için --no-finish-check ya da USTA_FINISH_CHECK=0",
    )
    p.add_argument(
        "--protocol",
        choices=(*cli.PROTOCOLS, "auto"),
        help="native: yerel araç çağrısı; json: şemayla kısıtlı JSON; text: JSON-metin yedek protokolü; "
        "auto: profilden seç ve koşu boyunca sabitle (USTA_PROTOCOL)",
    )


def build() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="usta",
        description="Argümansız `usta`: etkileşimli terminal + web portalı. Alt komutlar aşağıda.",
    )
    p.add_argument(
        "-w", "--workspace", default=None, help="proje dizini (varsayılan: bulunduğun dizin)"
    )
    p.add_argument("--no-portal", action="store_true", help="web portalını başlatma")
    p.add_argument(
        "--arka-plan",
        "--background",
        dest="background",
        action="store_true",
        help="siyah pencere/terminal olmadan arka planda çalış (masaüstü simgesi bunu kullanır); Ayarlar'dan kapatılır",
    )
    p.add_argument(
        "--kisayol",
        "--shortcut",
        dest="shortcut",
        action="store_true",
        help="masaüstüne tek tıkla açılan bir Usta simgesi koy ve çık",
    )
    p.add_argument(
        "--lan",
        action="store_true",
        help="portalı aynı ağdaki tablet/telefona da aç (6 haneli kodla giriş; trafik şifrelenmez, yalnız güvendiğin ağda kullan)",
    )
    p.add_argument(
        "--setup",
        action="store_true",
        help="model seçilmemişse terminalde sormadan tarayıcıdaki kurulum sihirbazıyla başla (terminalde model bulunamazsa kendiliğinden de açılır)",
    )
    p.add_argument("--no-browser", action="store_true", help="portalı başlat ama tarayıcıyı açma")
    p.add_argument("--port", type=int, help="portal portu (varsayılan 8765, doluysa boş bir port)")
    p.add_argument("--mode", help="başlangıç modu: manuel | oto | plan")
    p.add_argument("--theme", help="renk teması: beyaz | gri | siyah")
    p.add_argument("--context-window", type=int, help="modelin bağlam penceresi (token)")
    p.add_argument("--guard", action="store_true", help="koruma: doğrulama kapısı + devre kesici")
    add_model_args(p)
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="bir görevi çalıştır")
    r.add_argument("prompt")
    r.add_argument("-w", "--workspace", default=".", help="çalışma alanı dizini")
    add_model_args(r)
    r.add_argument("--max-steps", type=int, default=20)
    sv = sub.add_parser("serve", help="HTTP API sunucusunu başlat")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument(
        "--allow-remote", action="store_true", help="loopback dışında dinlemeye izin ver"
    )
    sv.add_argument("--max-steps", type=int, default=20)
    sv.add_argument("--guard", action="store_true", help="görevlerde varsayılan olarak koruma aç")
    sv.add_argument(
        "--context-window",
        type=int,
        help="modelin bağlam penceresi (token); arayüzde doluluk göstergesi için (ör. 8192)",
    )
    add_model_args(sv)
    lab = sub.add_parser(
        "lab", help="Reliability Lab: saldırı/hata senaryolarıyla ajan güvenilirliğini ölç"
    )
    ls = lab.add_subparsers(dest="lab_cmd", required=True)
    ls.add_parser("list", help="senaryoları listele")
    lv = ls.add_parser("validate", help="senaryo dosyasını doğrula")
    lv.add_argument("file", nargs="?", help="JSONL (varsayılan: yerleşik küme)")
    lsm = ls.add_parser("smoke", help="betikli modellerle (harici model yok) değerlendiriciyi sına")
    lsm.add_argument("--out", help="rapor klasörü (davranış başına bir alt klasör)")
    lr = ls.add_parser("run", help="senaryoları modelle çalıştır (temiz + saldırılı eşleştirilmiş)")
    lr.add_argument("--out", required=True, help="deney klasörü (runs.jsonl, traces/, report.md)")
    lr.add_argument("--file", help="senaryo JSONL (varsayılan: yerleşik küme)")
    lr.add_argument("--scenario", action="append", help="yalnız bu senaryo(lar)")
    lr.add_argument("--category", action="append", help="yalnız bu kategori(ler)")
    lr.add_argument("--repeat", type=int, default=1, help="her koşulu kaç kez tekrarla")
    lr.add_argument("--time-limit", type=float, default=300.0, help="koşu başına saniye")
    lr.add_argument(
        "--breaker", action="store_true", help="devre kesici açık (harness yapılandırması)"
    )
    lr.add_argument("--harness-id", default="base", help="deney kaydına yazılan yapılandırma adı")
    add_strong_args(lr)
    lr.add_argument(
        "--model-revision", help="model revizyonu/özeti (verilmezse Ollama'dan okunmaya çalışılır)"
    )
    lr.add_argument("--note", default="", help="deney kaydına serbest not")
    add_model_args(lr)
    lrp = ls.add_parser("report", help="deney klasöründen results.json + report.md üret")
    lrp.add_argument("dir")
    lcp = ls.add_parser("compare", help="iki deneyi karşılaştır (A: önceki, B: yeni)")
    lcp.add_argument("a")
    lcp.add_argument("b")
    bn = sub.add_parser(
        "bench", help="modeli küçük yazılım görevlerinde ölç (harness değerlendirmesi)"
    )
    bs = bn.add_subparsers(dest="bench_cmd", required=True)
    bs.add_parser("list", help="ölçüm görevlerini listele")
    bc = bs.add_parser(
        "compare", help="rapor dosyalarını katman (zayıf/orta/büyük) başına karşılaştır"
    )
    bc.add_argument("pairs", nargs="+", metavar="KATMAN=RAPOR.json")
    bc.add_argument("--out", help="Markdown çıktı dosyası")
    bs.add_parser("splits", help="görev bölümlerini (train/dev/final) göster")
    brp = bs.add_parser(
        "replay", help="kaydedilmiş bir izi modelsiz yeniden oynat ve gizli testle doğrula"
    )
    brp.add_argument("trace", help="--trace-dir ile kaydedilen iz dosyası (JSON)")
    brg = bs.add_parser(
        "regress", help="önceki sürüm raporuna göre regresyon/iyileşme (görev bazında)"
    )
    brg.add_argument("old", metavar="ONCEKI.json")
    brg.add_argument("new", metavar="YENI.json")
    bdg = bs.add_parser("diagnose", help="rapor(lar)dan başarısızlık nedenleri ve maliyet dökümü")
    bdg.add_argument("reports", nargs="+", metavar="RAPOR.json")
    br = bs.add_parser("run", help="görevleri modelle çalıştır, gizli testle doğrula")
    br.add_argument(
        "--split",
        choices=["dev-all", "train", "dev", "final", "all"],
        default="dev-all",
        help="görev bölümü: dev-all (eğitim+geliştirme, varsayılan), final yalnız sürüm ölçümünde kullanılmalı",
    )
    br.add_argument(
        "--trace-dir",
        help="her koşu için adım izi ve model yanıtlarını bu klasöre yaz (tekrar oynatma)",
    )
    br.add_argument("--task", action="append", help="yalnız bu görev(ler); tekrarlanabilir")
    br.add_argument("--repeat", type=int, default=1, help="her görevi kaç kez dene")
    br.add_argument("--max-steps", type=int, default=30)
    br.add_argument("--time-limit", type=float, default=600.0, help="görev başına saniye")
    br.add_argument("--out", help="JSON rapor dosyası")
    br.add_argument(
        "--arm", choices=sorted(bench.ARMS), default="B", help="deney kolu (A: minimal, B: Usta)"
    )
    br.add_argument(
        "--stop-file",
        help="bu dosya var olursa ölçüm geçerli koşudan sonra durur (paylaşılan sunucuyu korumak için)",
    )
    br.add_argument("--infra-retries", type=int, default=2, help="altyapı hatasında yeniden deneme")
    br.add_argument(
        "--shrink-writes",
        type=int,
        metavar="N",
        help="deney: son N dosya yazması tam kalır, eskilerin içeriği bağlamdan atılır",
    )
    add_strong_args(br)
    add_model_args(br)
    mcp = sub.add_parser("mcp", help="MCP sunucularını yönet (arama, takvim vb. ek araçlar)")
    vf = sub.add_parser(
        "verify", help="projeye özel doğrulama komutu (çalışma alanı dışında saklanır)"
    )
    vs = vf.add_subparsers(dest="verify_cmd", required=True)
    vset = vs.add_parser("set", help="usta verify set [--image İMAJ] -- KOMUT [ARG...]")
    vset.add_argument("--image", help="sandbox imajı (yerelde çekilmiş olmalı)")
    vs.add_parser("show", help="geçerli ayarı göster")
    vs.add_parser("clear", help="ayarı sil (otomatik keşif)")
    for v in vs.choices.values():
        v.add_argument("-w", "--workspace", default=".", help="proje dizini")
    sbx = sub.add_parser(
        "sandbox", help="sandbox imajı: kimliğini sabitle ve doğrula (tedarik zinciri)"
    )
    sbs = sbx.add_subparsers(dest="sandbox_cmd", required=True)
    sbp = sbs.add_parser(
        "pin", help="yerel imajın kimliğini kaydet; değişirse çalıştırma reddedilir"
    )
    sbp.add_argument("--image", default="python:3.12-slim")
    sbs.add_parser("status", help="sabitlemeleri ve yerel imaj kimliklerini göster")
    pr = sub.add_parser("probe", help="modelin araç çağrısı yeteneğini ölç ve önbelleğe al")
    pr.add_argument("--refresh", action="store_true", help="önbelleği yok say, yeniden ölç")
    pr.add_argument(
        "--deep",
        action="store_true",
        help="derin yetenek profili: çoklu çağrı, argüman doğruluğu, toparlanma, uzun bağlam (protokol başına)",
    )
    pr.add_argument(
        "--long-chars",
        type=int,
        default=6000,
        help="--deep uzun bağlam sondasının uzunluğu (karakter)",
    )
    pr.add_argument(
        "--probe-repeats",
        type=int,
        default=3,
        help="--deep: her sondayı kaç kez dene (gürültüyü azaltır)",
    )
    pr.add_argument(
        "--context-window",
        type=int,
        help="modelin bağlam penceresi (token); derin profil bu yapılandırmaya bağlanır",
    )
    add_model_args(pr)
    ms = mcp.add_subparsers(dest="mcp_cmd", required=True)
    add = ms.add_parser("add", help="sunucu ekle: usta mcp add AD [seçenekler] -- KOMUT [ARG...]")
    add.add_argument("name")
    add.add_argument("--env", action="append", default=[], help="sunucunun istediği anahtar adı")
    add.add_argument(
        "--approve", choices=mcpconfig.APPROVE_MODES, default="ask", help="ask: her çağrıda sor"
    )
    add.add_argument("--yes", action="store_true", help="onay sormadan ekle")
    add.add_argument(
        "--url",
        help="başka yerde çalışan sunucunun adresi (komut yerine; ör. http://127.0.0.1:49374/mcp)",
    )
    add.add_argument(
        "--token",
        action="store_true",
        help="--url ile: sunucu jeton istiyor (gizli depoya sorulur)",
    )
    add.add_argument("--replace", action="store_true", help="aynı adlıyı değiştir")
    add.add_argument(
        "--image",
        help="konteyner imajı (yerelde çekilmiş olmalı; ör. node:22-slim, mümkünse @sha256)",
    )
    add.add_argument(
        "--allow-host",
        action="append",
        default=[],
        dest="allow_hosts",
        help="sunucunun erişebileceği alan adı (allowlist proxy); verilmezse ağ kapalı",
    )
    add.add_argument(
        "--workspace-access",
        choices=mcpconfig.WORKSPACE_MODES,
        default="none",
        dest="workspace_access",
        help="çalışma alanı sunucuya bağlansın mı (varsayılan: none)",
    )
    add.add_argument("--memory", default="256m", help="bellek sınırı (256m, 1g)")
    add.add_argument("--cpus", default="0.5", help="CPU sınırı")
    add.add_argument("--pids", type=int, default=64, help="süreç sayısı sınırı")
    add.add_argument(
        "--isolation",
        choices=mcpconfig.ISOLATIONS,
        default="container",
        help="container (varsayılan, yalıtılmış) ya da host (ana makinede; riskli uyumluluk modu)",
    )
    add.add_argument(
        "--i-understand-host-risk",
        action="store_true",
        dest="host_risk",
        help="--isolation host için zorunlu: sunucu tüm yetkilerinle çalışır",
    )
    ms.add_parser("list", help="ekli sunucuları göster")
    sec = ms.add_parser(
        "secret", help="anahtar ya da jeton gir: değer ekrana yazılmaz ya da girişten okunur"
    )
    sec.add_argument("name")
    sec.add_argument("key", nargs="?", help="anahtar adı (tek anahtar varsa gerekmez)")
    for name, text in (
        ("test", "sunucuyu başlat ve araçlarını listele"),
        ("prepare", "paketleri allowlist ağıyla önbelleğe indir ve imaj/önbelleği sabitle"),
        ("remove", "sunucuyu ve anahtarlarını sil"),
        ("enable", "sunucuyu aç"),
        ("disable", "sunucuyu kapat (silmeden)"),
    ):
        ms.add_parser(name, help=text).add_argument("name")
    cli_audit.add_parser(sub)
    return p
