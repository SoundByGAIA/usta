def load_config(overrides=None):
    """Varsayılan ayarları overrides ile güncelleyip döndürür."""
    config = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_CONFIG.items()}
    if overrides:
        config.update(overrides)
    return config


DEFAULT_CONFIG = {"debug": False, "retries": 2, "tags": ["base"]}
