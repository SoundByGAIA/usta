DEFAULT_CONFIG = {"debug": False, "retries": 2, "tags": ["base"]}


def load_config(overrides=None):
    """Varsayılan ayarları overrides ile güncelleyip döndürür."""
    config = DEFAULT_CONFIG
    if overrides:
        config.update(overrides)
    return config
