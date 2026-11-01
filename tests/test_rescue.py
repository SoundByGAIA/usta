import json

import pytest

from usta.rescue import extract_calls

TOOLS = {"read_file", "write_file", "run"}


def names(content, tools=TOOLS):
    return [(c.name, c.arguments) for c in extract_calls(content, tools)]


@pytest.mark.parametrize(
    "content",
    [
        '{"name": "read_file", "arguments": {"path": "a.txt"}}',
        '```json\n{"name": "read_file", "arguments": {"path": "a.txt"}}\n```',
        '```\n{"name": "read_file", "arguments": {"path": "a.txt"}}\n```',
        '<tool_call>\n{"name": "read_file", "arguments": {"path": "a.txt"}}\n</tool_call>',
        '{"tool": "read_file", "arguments": {"path": "a.txt"}}',
        '{"function": "read_file", "parameters": {"path": "a.txt"}}',
        '{"name": "read_file", "arguments": "{\\"path\\": \\"a.txt\\"}"}',
        '  \n{"name": "read_file", "args": {"path": "a.txt"}}  \n',
    ],
)
def test_whole_content_tool_call_shapes_are_rescued(content):
    assert names(content) == [("read_file", {"path": "a.txt"})]


def test_several_calls_in_one_fence_or_list():
    c = '[{"name": "read_file", "arguments": {"path": "a"}}, {"name": "run", "arguments": {"command": "ls"}}]'
    assert [n for n, _ in names(c)] == ["read_file", "run"]


def test_ids_are_unique_and_stable_format():
    calls = extract_calls(
        '[{"name": "run", "arguments": {"command": "a"}}, {"name": "run", "arguments": {"command": "b"}}]',
        TOOLS,
    )
    assert len({c.id for c in calls}) == 2 and all(c.id.startswith("r") for c in calls)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "merhaba, dosyayı okudum",
        'Şöyle çağırabilirsin: {"name": "read_file", "arguments": {"path": "a"}} ama önce düşün',
        'Sonuç:\n```json\n{"name": "read_file", "arguments": {"path": "a"}}\n```\nBu bir örnek.',
        '{"name": "bilinmeyen_arac", "arguments": {}}',
        '{"name": "read_file", "arguments": [1, 2]}',
        '{"name": "read_file"}',
        '{"name": 5, "arguments": {}}',
        '{"user": "ali", "age": 5}',
        "{bozuk json",
        "[1, 2, 3]",
        '"sadece metin"',
    ],
)
def test_prose_examples_and_non_calls_are_not_rescued(content):
    assert names(content) == []


def test_missing_arguments_defaults_only_when_tool_takes_none_is_not_assumed():
    assert (
        names('{"name": "run"}') == []
    )  # argümansız çağrı kurtarılmaz: model yarım yazmış olabilir


def test_oversized_content_is_ignored():
    big = json.dumps({"name": "write_file", "arguments": {"path": "a", "content": "x" * 2_000_000}})
    assert names(big) == []


def test_no_tools_available_means_nothing_to_rescue():
    assert extract_calls('{"name": "read_file", "arguments": {"path": "a"}}', set()) == []
