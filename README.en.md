# Usta

English · [Türkçe](README.md)

A general-purpose, **open-source (Apache-2.0)** AI coding agent from Turkey. Type `usta` in a terminal: the agent works in your
project folder with tools, and a local web portal (`127.0.0.1`) shows the live stream, files and a preview.
Model-agnostic: any **OpenAI-compatible** endpoint (Ollama, llama.cpp, DeepSeek, OpenRouter, OpenAI...).

> Status: early development (v0.x). Commands and APIs may change. Design and threat model: [docs/design.md](docs/design.md) (Turkish).

The focus is not just "another LLM UI": it is a **harness that makes small and local models more reliable on real software work**
(tool calling, context management, verification loop, circuit breaker) and **measuring that honestly** (`usta bench`).
A feature becomes the default only if a measurement shows it helps.

## Quick start

```bash
git clone https://github.com/SoundByGAIA/usta.git usta && cd usta
uv venv && uv pip install -e .
ln -s "$PWD/.venv/bin/usta" ~/.local/bin/usta     # or: uv tool install --editable .
cd my-project
usta                                              # terminal + portal (opens in your browser)
```

On first run Usta lists the models at your endpoint (default Ollama `http://127.0.0.1:11434/v1`), you pick one, and it probes
the model's tool-calling ability (native `tool_calls` → JSON-schema → text protocol).

**Where are files written?** The folder where you start `usta` is the workspace; files are created right there (the full path is
printed on start). The agent can only write inside that folder. Starting in your home directory shows a warning; start in a
project folder instead.

## Terminal commands

| Command | |
|---|---|
| `/mod [manuel\|oto\|plan]` | **manual**: every approval is asked · **auto**: approval-needing actions run without asking (denials and sandbox still apply) · **plan**: read-only, produces a plan; apply it **phase by phase** or all at once after you approve |
| `/tema [beyaz\|gri\|siyah]` | color theme (shared with the portal) |
| `/koruma`, `/doğrula [cmd]` | verification gate + circuit breaker; project test command |
| `/diff`, `/geri` | show / undo the last task's changes |
| `/token` | token usage, provider cache hit and context fill |
| `/hafıza`, `/geçmiş [n]`, `/beceriler`, `/mcp` | project notes, past sessions, skills, extra tools |
| `/model [[api] name]`, `/portal` | list/switch model (all connected APIs), portal address |
| `/name text` | run skill `~/.usta/skills/name.md` |

Options: `usta --no-portal`, `--no-browser`, `--model`, `--endpoint`, `--mode`, `--theme`, `--context-window`, `--protocol`, `--model-timeout`.

## Portal

Shares the task manager with the terminal: a task started in one shows live in the other. It binds to `127.0.0.1` only and opens with a
**one-time short-lived code**, not a token.

- Tabs: **Stream, Changes, Memory, History, Preview**; colored diff, two-click undo, token/cache counter.
- **Steering while running:** messages you type during a task reach the agent at its next step.
- **File explorer:** browse, open, attach to task, upload files/folders, new file/folder, rename, delete.
- **Attachments:** text/Markdown files are added to the prompt *as data*.
- **APIs:** connect any number of OpenAI-compatible APIs; their models appear in the model picker and switch without leaving the session.
  Keys live only in `~/.usta/apis.json` (mode 0600) and are never shown again.
- **Preview:** static sites (HTML/CSS/JS) render in an isolated sandboxed frame (no access to the portal token or the network).
- **Tools:** skills (upload `.md`) and MCP servers from a reviewed catalog.
- **Size:** the UI auto-scales to the window/screen (90%–175% manual); 3 themes.

## Plan, then apply

In plan mode the agent only reads and writes a plan. After you approve:

- **Phase by phase (recommended):** the plan is split into checkable phases in `PLAN.md`; each phase runs as a **separate task with a fresh context**
  (read, implement, test, tick `- [x]`, stop). The chain stops by itself on no progress, error, cancel or circuit-breaker. It keeps context from
  ballooning on long jobs (needed for small 8K local models). **We do not claim total token savings** (see the measurement note below).
- **All at once:** the whole plan runs in one task.

**Measurement note (interim, single run):** same approved plan (a 24k-character commercial e-commerce site, DeepSeek, 200 steps/task limit, guard on). *All at once:* hit the step limit at 200 steps — 10.0M input tokens (94% served from the provider cache), 23 Python files, **no tests**, 0 items ticked in `PLAN.md`. *Phase by phase:* at phase 11/23, 18.2M input tokens, 41 files, **224 tests passing**. So phased execution spends more tokens overall but advances the job in verifiable steps, while the all-at-once run burned its step budget before reaching tests. One run only; do not generalize.

The plan is stored server-side and applied by id; the prompt is not re-sent.

## Security summary

Default: network off, no secrets, writes only inside the workspace. Commands run in a Docker sandbox; network only via an allowlist proxy.
The portal is local, token-protected and CSP-restricted; model output is always rendered as plain text. External content (web, files, MCP,
attachments, plans, memory) is given to the model as *data* inside nonce-marked blocks. Details and vulnerability reporting: [SECURITY.md](SECURITY.md).

## Measurement: usta bench (preliminary, read carefully)

`usta bench run --arm A|B|C|D` runs small real software tasks and verifies with **hidden tests the agent cannot see**
(A: shell only · B: Usta · C: + verification gate · D: + circuit breaker). `usta bench compare` prints per-tier tables with 95% intervals.
Infrastructure errors are not counted as failures; token cost is reported.

| Tier | Model | Arm: passed/total | Note |
|---|---|---|---|
| Weak | 4B local (5 tasks × 3) | A 1/15 · B 0/15 · C 1/15 | C ≈ 3.5× tokens; not statistically significant |
| Mid | 7B coder, JSON protocol (15 × 2) | B 0/30 · D 1/30 | D ≈ 4.5× tokens; model cannot produce solutions |
| Large (API) | DeepSeek (15 × 2) | A 30/30 · B 23/23¹ · C 29/30 · D 30/30 | tasks are easy for strong models (ceiling effect) |

¹ 7 infrastructure (network) errors not counted.

**We do not claim the harness improves success today**: it does no harm on strong models and is not a standalone fix for weak ones.
Samples are small and intervals wide. What we find while measuring is documented (e.g. some models write tool calls as text → rescue and
capability probe added; an early "drop written file bodies from context" experiment showed no benefit and is off by default).

## Development

```bash
uv venv && uv pip install -e '.[dev]'
make ci        # ruff + pytest (+ JS logic tests if node is installed)
```

Sandbox tests need Docker and a local `python:3.12-slim` image (`docker pull python:3.12-slim`; Usta never pulls images by itself); otherwise they are skipped.
Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
