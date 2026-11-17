"""MCP sunucularının HTTP uçları: yalnız katalogdan ekleme, serbest komut yok (bkz. mcpcatalog)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from usta import mcp_runtime, mcpcatalog, mcpconfig
from usta.api_models import EnabledIn, SecretIn, ServerName
from usta.mcp import McpClient, McpError


def register(api: APIRouter, home: Path) -> None:
    """MCP uçlarını `api` yönlendiricisine ekler."""

    def mcp_servers() -> dict[str, mcpconfig.Server]:
        try:
            return mcpconfig.load(home)
        except mcpconfig.McpConfigError as e:
            raise HTTPException(500, f"MCP yapılandırması: {e}") from None

    def mcp_server(name: str) -> mcpconfig.Server:
        server = mcp_servers().get(name)
        if server is None:
            raise HTTPException(404, "sunucu yok")
        return server

    @api.get("/mcp")
    def mcp_list() -> dict:
        servers = mcp_servers()
        out = []
        for s in servers.values():
            have = mcpconfig.resolve_env(home, s, os.environ)
            out.append(
                {
                    "name": s.name,
                    "enabled": s.enabled,
                    "approve": s.approve,
                    "command": list(s.command),
                    "env": [{"name": k, "set": k in have} for k in s.env],
                    "isolation": s.isolation,
                    "image": s.image,
                    "allow_hosts": list(s.allow_hosts),
                    "pinned": bool(s.pin_image and s.pin_cache),
                }
            )
        catalog = [
            {
                "id": e.id,
                "title": e.title,
                "description": e.description,
                "homepage": e.homepage,
                "command": list(e.command),
                "env": list(e.env),
                "image": e.image,
                "allow_hosts": list(e.allow_hosts),
                "added": e.id in servers,
            }
            for e in mcpcatalog.CATALOG
        ]
        return {"servers": out, "catalog": catalog}

    @api.post("/mcp/catalog/{entry_id}", status_code=201)
    def mcp_add_from_catalog(entry_id: str) -> dict:
        entry = mcpcatalog.get(entry_id)
        if entry is None:
            raise HTTPException(404, "katalogda yok")
        try:
            mcpconfig.add_server(
                home,
                entry.id,
                list(entry.command),
                list(entry.env),
                "ask",
                isolation="container",  # katalog sunucuları her zaman yalıtılmış çalışır
                image=entry.image,
                allow_hosts=list(entry.allow_hosts),
            )
        except mcpconfig.McpConfigError as e:
            raise HTTPException(409 if "zaten" in str(e) else 400, str(e)) from None
        return {"name": entry.id}

    @api.put("/mcp/{name}/secrets/{key}")
    def mcp_set_secret(name: ServerName, key: str, body: SecretIn) -> dict:
        mcp_server(name)
        try:
            mcpconfig.set_secret(home, name, key, body.value)
        except mcpconfig.McpConfigError as e:
            raise HTTPException(404 if "tanımlı değil" in str(e) else 400, str(e)) from None
        return {"set": True}

    @api.post("/mcp/{name}/enabled")
    def mcp_enable(name: ServerName, body: EnabledIn) -> dict:
        mcp_server(name)
        mcpconfig.set_enabled(home, name, body.enabled)
        return {"enabled": body.enabled}

    @api.delete("/mcp/{name}")
    def mcp_remove(name: ServerName) -> dict:
        mcp_server(name)
        mcpconfig.remove_server(home, name)
        return {"removed": name}

    @api.post("/mcp/{name}/test")
    def mcp_test(name: ServerName) -> dict:
        server = mcp_server(name)
        env = mcpconfig.resolve_env(home, server, os.environ)
        try:
            if server.isolation == "host":  # yalnız CLI'dan açıkça eklenmiş uyumluluk modu
                with McpClient(list(server.command), env, timeout=90) as client:
                    tools = client.list_tools()
            else:
                handle = mcp_runtime.start(server, home=home, env=env, workspace=None, timeout=90)
                try:
                    tools = handle.client.list_tools()
                finally:
                    handle.close()
        except McpError as e:
            raise HTTPException(502, str(e)) from None
        return {"tools": [{"name": t.name, "description": t.description[:200]} for t in tools]}

    @api.post("/mcp/{name}/prepare")
    def mcp_prepare(name: ServerName) -> dict:
        server = mcp_server(name)
        if server.isolation != "container":
            raise HTTPException(400, "yalnız konteyner izolasyonlu sunucular hazırlanır")
        try:
            iid, digest = mcp_runtime.prepare(
                server, home=home, env=mcpconfig.resolve_env(home, server, os.environ)
            )
            mcpconfig.set_pin(home, name, iid, digest)
        except McpError as e:
            raise HTTPException(502, str(e)) from None
        return {"pinned": True}
