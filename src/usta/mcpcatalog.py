"""Web arayüzünden tek tıkla eklenebilen MCP sunucuları (depoda sabit, gözden geçirilmiş liste).

Arayüz/API serbest komut eklemez: komutlar burada sürümü sabitlenmiş (tedarik zinciri) olarak durur.
Serbest komut ve `--approve allow` yalnız CLI'dan (`usta mcp add`) yapılır.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    description: str
    command: tuple[str, ...]
    env: tuple[str, ...]
    homepage: str
    image: str = "node:22-slim"  # yerelde çekilmiş olmalı; Usta imajı kendiliğinden çekmez
    allow_hosts: tuple[str, ...] = ()  # çalışma anında erişebileceği alan adları (allowlist proxy)


CATALOG: tuple[Entry, ...] = (
    Entry(
        id="brave-search",
        title="Brave Search (web arama)",
        description="Web, haber, görsel ve video araması. Brave'den ücretsiz bir API anahtarı gerekir. "
        "Aramalar Brave'e gider.",
        command=("npx", "-y", "@brave/brave-search-mcp-server@2.1.4", "--transport", "stdio"),
        env=("BRAVE_API_KEY",),
        homepage="https://github.com/brave/brave-search-mcp-server",
        allow_hosts=("api.search.brave.com",),
    ),
)


def get(entry_id: str) -> Entry | None:
    return next((e for e in CATALOG if e.id == entry_id), None)
