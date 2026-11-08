def parse(text, strict=False):
    """sku,items,qty satırlarını sözlük listesine çevirir. Boş ve '#' satırları atlanır, bozuk satırlar sessizce atlanır.

    strict=True ise (satirlar, hatalar) döner; hatalar bozuk satırların 1 tabanlı numaralarıdır.
    """
    rows = []
    errors = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3 or not parts[0]:
            errors.append(lineno)
            continue
        try:
            qty = int(parts[2])
            items = int(parts[1])
        except ValueError:
            errors.append(lineno)
            continue
        rows.append({"sku": parts[0], "items": items, "qty": qty})
    if strict:
        return rows, errors
    return rows


def report(rows, strict=False):
    """Toplam kalem, toplam adet ve sku listesi (virgülle) sözlüğü. strict=True ise (sozluk, uyarilar)."""
    result = {
        "items": sum(r["items"] for r in rows),
        "qty": sum(r["qty"] for r in rows),
        "sku": ",".join(r["sku"] for r in rows),
    }
    if not strict:
        return result
    warnings = [f"negatif adet: {r['sku']}" for r in rows if r["qty"] <= 0]
    warnings += [f"sku yok: {r['items']}" for r in rows if r["sku"] == ""]
    return result, warnings


def parse_and_report(text, strict=False):
    """Metni ayrıştırıp raporu döndürür. strict=True ise (sozluk, hatalar)."""
    if not strict:
        return report(parse(text))
    rows, errors = parse(text, strict=True)
    result, warnings = report(rows, strict=True)
    return result, [f"satir {n}" for n in errors] + warnings
