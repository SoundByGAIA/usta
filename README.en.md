# Usta

English · [Türkçe](README.md)

Usta is an open-source AI helper that does work on your computer. You say what you want ("make a page that shows my
bakery's menu"), and Usta reads and writes files and runs commands in a working folder. A small panel in your browser
shows what it is doing. Every change can be undone with two clicks.

It is written in Türkiye and licensed under Apache-2.0. We build it for two kinds of people:

- someone who has never written code: install, open, type in plain Turkish;
- a developer who wants real work out of a small local model (a 4 GB graphics card is enough).

You pick the model. It can run on your own machine (Ollama, llama.cpp) or come from an online service (DeepSeek,
OpenRouter, OpenAI, Gemini, Claude). Any OpenAI-compatible endpoint works. The interface is in Turkish.

> Early release (0.8.x). Commands and APIs may change.

## Install

If you don't code, are on Windows, or want to use a tablet, start here: [docs/baslangic.md](docs/baslangic.md) (Turkish).

Otherwise:

```bash
pip install usta          # or: uv tool install usta
cd my-project
usta                      # opens the terminal UI and the panel in your browser
```

On first run you pick a model. Usta runs a short check to learn how that model calls tools and uses the matching
protocol.

The folder you start Usta in is the workspace. Files are written there and nowhere else.

## Why another one?

Large models already do good work. Small models fall short in ways that hurt beginners: they say "I wrote the file" when
they didn't, ask for permission instead of acting, or make up facts. Usta exists to close that gap. We measure a change
before we turn it on by default, and we don't claim what we haven't measured.

What we have measured so far:

- **Say–do check** (on by default). If the model tries to finish without writing the file it was asked to write, it
  gets one short reminder. On a 9B model, task success went from 13/25 to 19/25. Attack success did not change.
  [docs/lab-sozeylem-olcumu.md](docs/lab-sozeylem-olcumu.md)
- **Website requests from non-coders** (experimental, `USTA_SITE_STEPS=1`). Usta builds the page frame, inserts the
  user's own facts and the countdown, and lets the model write only a short text. Three small models, 45 runs: 45 correct,
  12–21 seconds each. Asked to write the whole page in one go, the same models got 10 of 45 right.
  [docs/lab-site-olcumu.md](docs/lab-site-olcumu.md)
- Telling a small model "don't write a phone number or opening hours" made it write exactly those, 5 times out of 5. Our
  prompts are phrased positively because of this. Same document.

We also write down what didn't work. Turning thinking down made small models worse
([docs/lab-dusunme-olcumu.md](docs/lab-dusunme-olcumu.md)). A verification gate and a circuit breaker did not rescue a
weak model on their own ([docs/v0.2.0-raporu.md](docs/v0.2.0-raporu.md)). These reports are in Turkish.

## Safety

Someone who can't read code can't check what an AI is doing in the background. So the rules don't depend on the model
behaving well:

- Commands run in a Docker box with the network off. The network opens only to addresses you allow.
- Writes stay inside the workspace. Each task's changes can be undone with two clicks.
- If a web page or file Usta reads tells it to write somewhere, Usta asks you first (taint gate).
- `.env`, key and password files are not read unless you asked for them.
- Files that can run on their own (`.vscode/`, git hooks, CI configs) need your approval before they are written.
- Extra tools (MCP servers) run in their own box. The panel only opens from this computer.

Details, fixed vulnerabilities and how to report one: [SECURITY.md](SECURITY.md).

## What's in it

- **Panel:** live stream, colored diff, undo, file browser, site preview, past tasks. A task started in the terminal
  shows up in the panel too.
- **Modes:** `manuel` (asks before each risky step), `oto` (doesn't ask; hard limits still apply), `plan` (reads, writes
  a plan, and carries it out step by step once you approve).
- **Profile:** tell Usta once how to address you and how to explain things.
- **Shared memory at home:** a few computers at home share notes. Pairing uses a 6-digit code, requests are signed, and
  notes coming from another machine are not used until you approve them.
- **Skills:** teach Usta a recurring job once. It proposes the recipe and you save it.
- **Other AI programs:** if Claude Code, Codex, OpenCode, DeepSeek Harness or Hermes is installed, Usta can hand work to
  them. It asks every time and gives read-only access by default.
- **Tablet and phone:** `usta --lan` opens the panel to your home network behind a PIN.

Most-used terminal commands:

| Command | |
|---|---|
| `/mod manuel\|oto\|plan` | working mode |
| `/diff`, `/geri` | last task's changes, undo |
| `/model` | switch model |
| `/hafıza`, `/geçmiş` | project notes, past tasks |
| `/token` | tokens spent and context fill |

One-off task: `usta run "summarize not.txt" -w ./folder`. API server: `usta serve`.

## Measurement tools

- `usta lab` runs the same task clean and under attack (poisoned file, fake instructions, exfiltration attempts) and
  judges the tool calls the model actually made, not what it said. [docs/reliability-lab.md](docs/reliability-lab.md)
- `usta bench` runs small software tasks and checks them with tests the agent can't see.
- `usta probe` measures and stores a model's tool-calling ability.

## Development

```bash
git clone https://github.com/SoundByGAIA/usta.git && cd usta
uv venv && uv pip install -e '.[dev]'
make ci        # ruff + pytest
```

Sandbox tests need Docker and the `python:3.12-slim` image; without them those tests are skipped. See
[CONTRIBUTING.md](CONTRIBUTING.md). Architecture and threat model (Turkish): [docs/design.md](docs/design.md).

## License and credits

Apache-2.0, see [LICENSE](LICENSE).

Ordis: Uğur Can Leba (Ordis architect, founder), Claude (Anthropic; Ordis architect, AI co-developer), Berke Dündar
(security and development, CTO), Ceren Yıldız (head teacher and localization). The names are listed in [NOTICE](NOTICE)
and must be kept in derivative works under Apache-2.0 section 4(d).
