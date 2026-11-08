def parse(text):
    """sku,items,qty satırlarını sözlük listesine çevirir. Boş ve '#' satırları atlanır, bozuk satırlar sessizce atlanır."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3 or not parts[0]:
            continue
        try:
            qty = int(parts[2])
            items = int(parts[1])
        except ValueError:
            continue
        rows.append({"sku": parts[0], "items": items, "qty": qty})
    return rows


def report(rows):
    """Toplam kalem, toplam adet ve sku listesi (virgülle) sözlüğü."""
    return {
        "items": sum(r["items"] for r in rows),
        "qty": sum(r["qty"] for r in rows),
        "sku": ",".join(r["sku"] for r in rows),
    }


def parse_and_report(text):
    """Metni ayrıştırıp raporu döndürür."""
    return report(parse(text))
