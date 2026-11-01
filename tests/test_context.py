from usta import context
from usta.agent import Agent
from usta.audit import AuditLog
from usta.models import Message, ModelResponse, ToolCall, Usage
from usta.policy import Policy
from usta.tools import ToolContext, build_registry


def convo(n_pairs=6, size=3000):
    msgs = [Message("system", "sistem"), Message("user", "görev")]
    for i in range(n_pairs):
        msgs.append(
            Message("assistant", None, [ToolCall(f"c{i}", "read_file", {"path": f"f{i}.py"})])
        )
        msgs.append(Message("tool", "x" * size, tool_call_id=f"c{i}"))
    return msgs


def valid_structure(msgs):
    ids = set()
    for m in msgs:
        if m.role == "assistant":
            ids = {c.id for c in m.tool_calls}
        elif m.role == "tool":
            assert m.tool_call_id in ids, "araç mesajı eşleşen çağrıdan sonra gelmeli"
    return True


def test_estimate_tokens_is_chars_over_three_plus_overhead():
    msgs = [Message("user", "a" * 300)]
    assert 90 <= context.estimate_tokens(msgs) <= 130


def test_estimate_counts_tool_call_arguments_too():
    small = [
        Message("assistant", None, [ToolCall("c", "write_file", {"path": "a", "content": "x"})])
    ]
    big = [
        Message(
            "assistant", None, [ToolCall("c", "write_file", {"path": "a", "content": "x" * 3000})]
        )
    ]
    assert context.estimate_tokens(big) > context.estimate_tokens(small) + 800


def test_truncate_keeps_head_and_tail_with_notice():
    text = "BAŞ" + "-" * 10_000 + "SON"
    out = context.truncate_result(text, 1000)
    assert len(out) < 1300 and out.startswith("BAŞ") and out.endswith("SON") and "atlandı" in out
    assert context.truncate_result("kısa", 1000) == "kısa"


def test_result_limit_scales_with_window_and_has_floor():
    assert context.result_limit(8192) < context.result_limit(32768)
    assert context.result_limit(512) >= 1500
    assert context.result_limit(None) is None


def test_compact_replaces_old_tool_results_keeps_recent_and_structure():
    msgs = convo()
    saved = context.compact(msgs, keep_last=4)
    assert saved > 10_000 and valid_structure(msgs)
    assert msgs[0].content == "sistem" and msgs[1].content == "görev"
    old = [m for m in msgs if m.role == "tool"][:4]
    assert all(
        "x" * 100 not in m.content and "atıldı" in m.content and "read_file" in m.content
        for m in old
    )
    recent = [m for m in msgs if m.role == "tool"][-2:]
    assert all(m.content == "x" * 3000 for m in recent)


def test_compact_stubs_large_written_content_in_old_assistant_calls():
    msgs = [Message("system", "s"), Message("user", "g")]
    msgs.append(
        Message(
            "assistant",
            None,
            [ToolCall("w", "write_file", {"path": "a.py", "content": "kod\n" * 2000})],
        )
    )
    msgs.append(Message("tool", "yazıldı", tool_call_id="w"))
    for i in range(4):
        msgs.append(Message("assistant", "düşünce", []))
        msgs.append(Message("user", "devam"))
    context.compact(msgs, keep_last=4)
    args = msgs[2].tool_calls[0].arguments
    assert args["path"] == "a.py" and len(args["content"]) < 200 and "yazıldı" in args["content"]


def test_compact_is_idempotent_and_returns_zero_when_nothing_to_do():
    msgs = convo()
    context.compact(msgs, keep_last=4)
    assert context.compact(msgs, keep_last=4) == 0
    assert context.compact([Message("system", "s"), Message("user", "g")], keep_last=4) == 0


# --- ajan entegrasyonu ---------------------------------------------------------------------
class Seq:
    def __init__(self, *r):
        self.r, self.seen = list(r), []
        self.usage = Usage()

    def chat(self, messages, tools=None):
        self.seen.append(
            [Message(m.role, m.content, list(m.tool_calls), m.tool_call_id) for m in messages]
        )
        return self.r.pop(0) if self.r else ModelResponse("bitti")


def agent(tmp_path, model, events, **kw):
    return Agent(
        model,
        build_registry(ToolContext(root=tmp_path, max_read=100_000)),
        Policy(tmp_path),
        AuditLog(tmp_path.parent / f"{tmp_path.name}-ctx.jsonl"),
        on_event=lambda t, d: events.append((t, d)),
        max_steps=30,
        **kw,
    )


def reads(n):
    return [
        ModelResponse(None, [ToolCall(f"r{i}", "read_file", {"path": "big.txt"})]) for i in range(n)
    ]


def test_agent_truncates_huge_tool_results_to_window_budget(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 50_000)
    model = Seq(*reads(1), ModelResponse("bitti"))
    agent(tmp_path, model, [], context_window=8192).run("oku")
    tool = next(m for m in model.seen[1] if m.role == "tool")
    assert len(tool.content) <= context.result_limit(8192) + 400 and "atlandı" in tool.content


def test_agent_compacts_when_window_nearly_full_and_emits_event(tmp_path):
    (tmp_path / "big.txt").write_text("y" * 2500)
    events = []
    model = Seq(*reads(10), ModelResponse("bitti"))
    agent(tmp_path, model, events, context_window=4096).run("oku")
    compacted = [d for t, d in events if t == "compacted"]
    assert compacted and compacted[0]["saved_chars"] > 0
    last = model.seen[-1]
    assert valid_structure(last)
    assert sum(1 for m in last if m.role == "tool" and "atıldı" in m.content) >= 1
    assert context.estimate_tokens(last) < 4096 * 0.95


def test_no_window_means_no_budgeting_or_compaction(tmp_path):
    (tmp_path / "big.txt").write_text("z" * 20_000)
    events = []
    model = Seq(*reads(4), ModelResponse("bitti"))
    agent(tmp_path, model, events).run("oku")
    assert not [1 for t, _ in events if t == "compacted"]
    assert all(len(m.content) == 20_000 for m in model.seen[-1] if m.role == "tool")


def _write(i, content, ok=True):
    from usta.models import Message, ToolCall

    cid = f"w{i}"
    return [
        Message(
            "assistant",
            None,
            [ToolCall(cid, "write_file", {"path": f"f{i}.txt", "content": content})],
        ),
        Message("tool", "yazıldı" if ok else "hata: izin yok", tool_call_id=cid),
    ]


def test_shrink_writes_keeps_last_n_and_stubs_older_successful_writes():
    from usta.context import shrink_writes
    from usta.models import Message

    big = "satır\n" * 200
    msgs = [Message("system", "s"), Message("user", "görev")]
    for i in range(4):
        msgs += _write(i, big)
    saved = shrink_writes(msgs, keep=2)
    bodies = [m.tool_calls[0].arguments["content"] for m in msgs if m.role == "assistant"]
    assert bodies[2] == big and bodies[3] == big  # son 2 tam
    assert all(b.startswith("[") and "atıldı" in b and "read_file" in b for b in bodies[:2])
    assert saved > 2 * len(big) - 500
    assert shrink_writes(msgs, keep=2) == 0  # ikinci çağrı yeniden kırpmaz (idempotent)
    # araç çağrısı/sonuç eşleşmesi bozulmadı
    ids = [c.id for m in msgs if m.role == "assistant" for c in m.tool_calls]
    assert ids == [m.tool_call_id for m in msgs if m.role == "tool"]


def test_shrink_writes_leaves_failed_writes_and_short_content():
    from usta.context import shrink_writes
    from usta.models import Message

    big = "x" * 1000
    msgs = [Message("system", "s"), Message("user", "g")]
    msgs += _write(0, big, ok=False) + _write(1, "kısa") + _write(2, big) + _write(3, big)
    shrink_writes(msgs, keep=1)
    bodies = [m.tool_calls[0].arguments["content"] for m in msgs if m.role == "assistant"]
    assert bodies[0] == big  # başarısız yazma: yeniden denenebilir, dokunulmaz
    assert bodies[1] == "kısa"  # kısa içerik özetlenmez
    assert bodies[2].startswith("[") and bodies[3] == big


def test_agent_shrinks_before_model_call(tmp_path):
    from usta.agent import Agent
    from usta.audit import AuditLog
    from usta.models import ModelResponse, ToolCall
    from usta.policy import Policy
    from usta.tools import ToolContext, build_registry

    seen = []

    class M:
        def __init__(self):
            self.n = 0

        def chat(self, messages, tools=None):
            self.n += 1
            seen.append(
                [
                    c.arguments.get("content", "")[:1]
                    for m in messages
                    if m.role == "assistant"
                    for c in m.tool_calls
                ]
            )
            if self.n <= 4:
                return ModelResponse(
                    None,
                    [
                        ToolCall(
                            f"c{self.n}",
                            "write_file",
                            {"path": f"a{self.n}.txt", "content": "z" * 500},
                        )
                    ],
                )
            return ModelResponse("bitti", [])

    agent = Agent(
        M(),
        build_registry(ToolContext(root=tmp_path)),
        Policy(tmp_path),
        AuditLog(tmp_path.parent / "a.jsonl"),
        approver=lambda *_: True,
        shrink_writes=1,
    )
    agent.run("yaz")
    assert seen[-1].count("[") == 3 and seen[-1][-1] == "z"  # 4 yazmadan 3'ü kırpıldı, sonuncu tam
    assert (tmp_path / "a1.txt").read_text() == "z" * 500  # diskteki dosya etkilenmez


def test_agent_calibrates_token_estimate_from_provider_usage(tmp_path):
    """Sağlayıcı tahminimizin 2 katını sayıyorsa sıkıştırma daha erken devreye girer."""
    from usta.agent import Agent
    from usta.audit import AuditLog
    from usta.models import ModelResponse, ToolCall, Usage
    from usta.policy import Policy
    from usta.tools import ToolContext, build_registry

    def run(real_factor):
        events = []

        class M:
            def __init__(self):
                self.usage, self.n = Usage(), 0

            def chat(self, messages, tools=None):
                from usta.context import estimate_tokens

                self.n += 1
                self.usage.requests += 1
                self.usage.last_prompt = int(estimate_tokens(messages) * real_factor)
                if self.n <= 8:
                    return ModelResponse(
                        None,
                        [
                            ToolCall(
                                f"c{self.n}",
                                "write_file",
                                {"path": f"f{self.n}.txt", "content": "k" * 900},
                            )
                        ],
                    )
                return ModelResponse("bitti", [])

        agent = Agent(
            M(),
            build_registry(ToolContext(root=tmp_path / str(real_factor))),
            Policy(tmp_path / str(real_factor)),
            AuditLog(tmp_path / f"a{real_factor}.jsonl"),
            approver=lambda *_: True,
            context_window=3000,
            on_event=lambda t, d: events.append(t),
        )
        (tmp_path / str(real_factor)).mkdir()
        agent.run("yaz")
        return events.count("compacted"), agent._tok_ratio

    c1, r1 = run(1.0)
    c2, r2 = run(2.0)
    assert 0.9 < r1 < 1.2 and 1.7 < r2 < 2.3  # kalibrasyon gerçek oranı yakalar
    assert c2 >= c1  # gerçekte daha pahalı bağlam: sıkıştırma en az o kadar sık
