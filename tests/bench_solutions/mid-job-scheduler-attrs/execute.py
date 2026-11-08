def retry_delay(attempt):
    """Ardışık denemeler arasında beklenecek saniye (deneme 1'den başlar): 1, 4, 9, ..."""
    return attempt * attempt
