def paginate(total, page_size, page=1):
    """Bir sayfanın {\"page\", \"pages\", \"offset\", \"size\"} bilgisini döndürür."""
    if total < 0 or page_size < 1 or page < 1:
        raise ValueError("total >= 0, page_size >= 1, page >= 1 olmalı")
    pages = (total + page_size - 1) // page_size
    if page > max(1, pages):
        raise ValueError("sayfa aralık dışında")
    offset = (page - 1) * page_size
    if pages == 0:
        size = 0
    elif page < pages:
        size = page_size
    else:
        size = total - offset
    return {"page": page, "pages": pages, "offset": offset, "size": size}


def page_links(total, page_size, page, window=2):
    """Gezinme bağlantısı listesini (sayfa numaraları ve \"...\") döndürür."""
    info = paginate(total, page_size, page)
    pages = info["pages"]
    if pages == 0:
        return []
    out = [1]
    previous = 1
    for p in range(max(1, page - window), min(pages, page + window) + 1):
        if p <= 1:
            continue
        if p - previous > 1:
            out.append("...")
        out.append(p)
        previous = p
    if pages > previous and pages - previous > 1:
        out.append("...")
    if pages > previous:
        out.append(pages)
    return out
