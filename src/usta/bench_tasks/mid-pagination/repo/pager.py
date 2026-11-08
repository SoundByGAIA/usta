def paginate(total, page_size, page=1):
    """Bir sayfanın {\"page\", \"pages\", \"offset\", \"size\"} bilgisini döndürür."""
    raise NotImplementedError


def page_links(total, page_size, page, window=2):
    """Gezinme bağlantısı listesini (sayfa numaraları ve \"...\") döndürür."""
    raise NotImplementedError
