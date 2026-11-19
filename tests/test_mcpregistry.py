from usta import mcpregistry

BRAVE = {
    "name": "io.github.brave/brave-search-mcp-server",
    "description": "Brave Search MCP Server",
    "repository": {"url": "https://github.com/brave/brave-search-mcp-server", "source": "github"},
    "version": "2.1.5",
    "packages": [
        {
            "registryType": "npm",
            "identifier": "@brave/brave-search-mcp-server",
            "version": "2.1.5",
            "transport": {"type": "stdio"},
            "environmentVariables": [
                {
                    "name": "BRAVE_API_KEY",
                    "isRequired": True,
                    "isSecret": True,
                    "description": "API key",
                }
            ],
        }
    ],
}
IMPOSTOR = dict(
    BRAVE,
    name="io.github.kotu/brave-search-mcp-server",
    repository={"url": "https://github.com/kotu/brave-search-mcp-server"},
)
TIME = {
    "name": "io.github.ornek/zaman",
    "version": "1.0.0",
    "repository": {"url": "https://github.com/ornek/zaman"},
    "packages": [
        {
            "registryType": "pypi",
            "identifier": "mcp-server-time",
            "version": "2026.1.1",
            "transport": {"type": "stdio"},
            "packageArguments": [
                {"type": "named", "name": "--local-timezone", "value": "Europe/Istanbul"}
            ],
        }
    ],
}
REMOTE = {
    "name": "com.ornek/uzak",
    "version": "1",
    "remotes": [{"type": "streamable-http", "url": "https://x"}],
}
ASKS = {
    "name": "io.github.ornek/soran",
    "version": "1",
    "packages": [
        {
            "registryType": "npm",
            "identifier": "soran",
            "version": "1",
            "transport": {"type": "stdio"},
            "packageArguments": [{"type": "positional", "valueHint": "dizin", "isRequired": True}],
        }
    ],
}


def fake_get(results):
    calls = []

    def get(path):
        calls.append(path)
        if "/versions/" in path:
            name = path.split("/servers/")[1].split("/versions/")[0].replace("%2F", "/")
            return {"server": next(s for s in results if s["name"] == name)}
        return {"servers": [{"server": s} for s in results]}

    get.calls = calls
    return get


def test_github_link_finds_only_the_matching_repository():
    get = fake_get([IMPOSTOR, BRAVE])
    (e,) = mcpregistry.search("https://github.com/brave/brave-search-mcp-server/tree/main", get)
    assert e.name == "io.github.brave/brave-search-mcp-server" and e.verified
    assert (
        e.command == ("npx", "-y", "@brave/brave-search-mcp-server@2.1.5")
        and e.image == "node:22-slim"
    )
    assert e.env == [
        {"name": "BRAVE_API_KEY", "required": True, "secret": True, "description": "API key"}
    ]
    assert "search=brave-search-mcp-server" in get.calls[0]


def test_package_name_and_registry_name_match_exactly():
    get = fake_get([IMPOSTOR, BRAVE, TIME])
    assert [e.name for e in mcpregistry.search("@brave/brave-search-mcp-server", get)] == [
        "io.github.kotu/brave-search-mcp-server",
        "io.github.brave/brave-search-mcp-server",
    ]
    assert [e.name for e in mcpregistry.search("io.github.ornek/zaman", get)] == [
        "io.github.ornek/zaman"
    ]


def test_impostor_namespace_is_not_verified_when_repository_differs():
    e = mcpregistry.parse(dict(IMPOSTOR, repository={"url": "https://github.com/brave/x"}))
    assert not e.verified


def test_pypi_with_fixed_arguments_and_unsupported_shapes():
    t = mcpregistry.parse(TIME)
    assert t.command == ("uvx", "mcp-server-time==2026.1.1", "--local-timezone", "Europe/Istanbul")
    assert t.image.startswith("ghcr.io/astral-sh/uv")
    assert "internetteki" in mcpregistry.parse(REMOTE).reason
    assert "değer" in mcpregistry.parse(ASKS).reason and not mcpregistry.parse(ASKS).command


def test_fetch_reloads_the_entry_from_the_registry():
    get = fake_get([BRAVE])
    e = mcpregistry.fetch("io.github.brave/brave-search-mcp-server", "2.1.5", get)
    assert e.command[2] == "@brave/brave-search-mcp-server@2.1.5"
    assert get.calls == ["/servers/io.github.brave%2Fbrave-search-mcp-server/versions/2.1.5"]
