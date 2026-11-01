"""MCP sunucularını görev süresince yönetir ve araçlarını Usta araç kaydına çevirir.

Sunucudan gelen her şey (ad, açıklama, şema, sonuç) güvenilmezdir: adlar temizlenir ve
`mcp__<sunucu>__<araç>` önekiyle ayrılır, açıklama kısaltılır, büyük şema genel şemayla
değiştirilir, sonuç nonce'lu HARİCİ-İÇERİK işaretleriyle veri olarak sarılır.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Self

from usta import mcpconfig
from usta.fetch import _clean, wrap_external
from usta.mcp import McpClient, McpError
from usta.tools import Tool, ToolError

MAX_NAME = 64
MAX_DESCRIPTION = 300
MAX_SCHEMA_BYTES = 8_000
GENERIC_SCHEMA = {"type": "object", "additionalProperties": True}


def qualified_name(server: str, tool: str, taken: set[str]) -> str:
    """`mcp__<sunucu>__<araç>`; model API'sinin ad kuralına uyar, çakışmaz, kararlıdır."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", tool) or "arac"
    name = f"mcp__{server}__{safe}"
    if len(name) > MAX_NAME or name in taken or safe != tool:
        digest = hashlib.sha1(f"{server}\0{tool}".encode()).hexdigest()[:8]
        if name in taken or len(name) > MAX_NAME or safe != tool:
            name = f"{name[: MAX_NAME - 9]}_{digest}"
    taken.add(name)
    return name


def _schema(raw: dict) -> dict:
    try:
        ok = raw.get("type") == "object" and len(json.dumps(raw)) <= MAX_SCHEMA_BYTES
    except (TypeError, ValueError):
        ok = False
    return raw if ok else dict(GENERIC_SCHEMA)


class McpSession:
    def __init__(
        self,
        servers: Iterable[mcpconfig.Server],
        home: Path | None,
        environ: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        cancel: threading.Event | None = None,
    ):
        self.servers = [s for s in servers if s.enabled]
        self.home, self.timeout, self.cancel = home, timeout, cancel
        self.environ = os.environ if environ is None else environ
        self.tools: list[Tool] = []
        self.modes: dict[str, str] = {}
        self.warnings: list[str] = []
        self.clients: list[McpClient] = []

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        taken: set[str] = set()
        for srv in self.servers:
            if self.cancel is not None and self.cancel.is_set():
                break
            env = mcpconfig.resolve_env(self.home, srv, self.environ) if self.home else {}
            client = McpClient(list(srv.command), env, timeout=self.timeout)
            try:
                client.start()
                found = client.list_tools()
            except McpError as e:
                client.close()
                self.warnings.append(f"MCP sunucusu '{srv.name}' başlatılamadı: {e}")
                continue
            self.clients.append(client)
            for t in found:
                name = qualified_name(srv.name, t.name, taken)
                desc = _clean(t.description)[:MAX_DESCRIPTION]
                self.modes[name] = srv.approve
                self.tools.append(
                    Tool(
                        name,
                        f"[MCP: {srv.name}] {desc}".strip(),
                        _schema(t.schema),
                        self._caller(client, srv.name, t.name),
                    )
                )

    def _caller(self, client: McpClient, server: str, tool: str):
        def call(args: dict) -> str:
            if not isinstance(args, dict):
                raise ToolError("geçersiz argüman tipi")
            try:
                text = client.call_tool(tool, args, cancel=self.cancel)
            except McpError as e:  # hata metni de sunucudan gelir: veri olarak sarılır
                raise ToolError(
                    wrap_external(
                        f"MCP sunucusu: {server}", str(e), origin="MCP sunucusundan (hata)"
                    )
                ) from e
            return wrap_external(f"MCP sunucusu: {server}", text, origin="MCP sunucusundan")

        return call

    def close(self) -> None:
        for c in self.clients:
            c.close()
        self.clients = []
