from pricing import apply_discount


def total(items, discount_percent=0):
    """items: (ad, birim_fiyat, adet) listesi. İndirim yüzde olarak verilir (10 = %10)."""
    subtotal = sum(price * qty for _, price, qty in items)
    return apply_discount(subtotal, discount_percent / 100)
