# OpenCode — Context
Last updated: April 14, 2026

## What it is
OpenCode is Sam's primary agentic coding CLI, run directly in Termius inside repos on ubuntu-homelab. Uses local inference via Bifrost → llama-swap. Replaces BooCode (abandoned). Not CodeNomad — OpenCode runs standalone in terminal sessions.

## Location
- Binary: `/home/samkintop/.opencode/bin/opencode`
- Global config: `~/.config/opencode/opencode.json`
- TUI config: `~/.config/opencode/tui.json`
- Global rules: `~/.config/opencode/AGENTS.md`
- Agents: `~/.config/opencode/agents/*.md`
- Commands: `~/.config/opencode/commands/*.md`
- Skills: `~/.config/opencode/skills/*/SKILL.md`
- Snippets: `~/.config/opencode/snippet/*.md`
- Plugins (npm, auto-installed): `~/.cache/opencode/packages/`
- Plugins (local): `~/.config/opencode/plugins/`
- Theme: `~/.config/opencode/themes/homelab.json`

## Provider
Custom provider `bifrost` using `@ai-sdk/openai-compatible` pointed at `http://100.114.205.53:8080/v1` (Bifrost gateway on ubuntu-homelab). All models accessed via `bifrost/<provider>/<model-id>` format.

### Models configured
| Model ID | Name | Hardware | Context | Notes |
|----------|------|----------|---------|-------|
| `llama-desktop/qwopus27b` | Qwopus 27B | RTX 5090 (sam-desktop) | 65536 | Default model. Q6_K, 22.1GB. Daily driver for coding + chat. |
| `llama-desktop/qwen3-coder-30b` | Qwen3 Coder 30B | RTX 5090 | 65536 | Coding-focused |
| `llama-desktop/qwen3-coder-next` | Qwen3 Coder Next | RTX 5090 | 65536 | Coding alt |
| `llama-desktop/gemma-4-26b-a4b` | Gemma 4 26B | RTX 5090 | 65536 | General/chat |
| `llama-desktop/nemotron-cascade-2` | Nemotron Cascade 2 | RTX 5090 | 65536 | Reasoning |
| `tabbyapi-gpu/Qwopus3.5-9B-v3-6bpw-exl3` | Qwopus 9B EXL3 | RTX 4080S (gpu machine) | 65536 | Lightweight; used for compaction/title/summary agents |

### Agent → Model routing
| Agent | Model | Temperature | Purpose |
|-------|-------|-------------|---------|
| build | qwopus27b | 0.2 | Full dev with all tools |
| plan | qwopus27b | 0.2 | Analysis, read-only by default |
| architect | qwopus27b | 0.3 | Primary agent, plan-only, no edits |
| reviewer | (inherits) | 0.1 | Subagent, read-only code review |
| researcher | (inherits) | 0.3 | Subagent, read-only exploration |
| compaction | Qwopus 9B EXL3 | — | Hidden, auto session compaction |
| title | Qwopus 9B EXL3 | — | Hidden, auto session title |
| summary | Qwopus 9B EXL3 | — | Hidden, auto session summary |

---

## Plugins (npm — in opencode.json `plugin` array)
| Plugin | Purpose |
|--------|---------|
| `opencode-dynamic-context-pruning` | Prunes stale tool outputs from conversation history |
| `opencode-sessions` | Multi-agent session management: message, new, compact, fork modes |
| `opencode-snip` | Prefixes shell commands with `snip` to reduce output tokens 60-90% |
| `envsitter-guard` | Prevents agent from reading/editing `.env*` files; exposes safe inspection tools |
| `opencode-handoff` | `/handoff` command to create focused continuation prompts for new sessions |
| `@tarquinen/opencode-dcp@latest` | Differential Context Protocol |
| `@0xsero/open-queue` | Queues messages while agent is thinking instead of interrupting |
| `opencode-snippets` | Hashtag-based inline snippet expansion (`#snippet` anywhere in messages) |
| `opencode-shell-strategy` | Teaches LLM to use non-interactive shell flags (no TTY in OpenCode) |

### Plugin install location
npm plugins auto-install to `~/.cache/opencode/packages/` via bun on startup. Bun installed at `/home/samkintop/.bun/bin/bun` (v1.3.12).

---

## Plugins (local — `~/.config/opencode/plugins/`)
| Plugin | Purpose |
|--------|---------|
| `shell-strategy/` | Git clone of JRedeker/opencode-shell-strategy (also installed via npm — duplicate, npm version takes precedence) |

---

## Skills (`~/.config/opencode/skills/`)
| Skill | Source | Purpose |
|-------|--------|---------|
| `frontend-design` | anthropics/skills | Production-grade frontend UI guidance, anti-AI-slop aesthetics |
| `code-review` | anthropics/knowledge-work-plugins | Code review methodology + severity classification |
| `task-management` | anthropics/knowledge-work-plugins | TODO/task tracking in sessions |
| `react-vite-best-practices` | asyrafhussin/agent-skills | React + Vite patterns (matches Sam's stack) |
| `vercel-react-best-practices` | vercel-labs/agent-skills | React best practices from Vercel |
| `web-design-guidelines` | vercel-labs/agent-skills | Web design principles |

Skills also installed to `~/.agents/skills/` by `npx skills add`. OpenCode discovers from both paths.

---

## Agents (`~/.config/opencode/agents/`)

### Primary agents (Tab to switch)
- **build** — default, all tools, full dev
- **plan** — built-in, read-only analysis, bash/edit = ask
- **architect** — custom, plan-only, no edits, decomposes into 5-20 min steps, outputs Cursor prompts

### Subagents (@mention to invoke)
- **reviewer** — read-only code review, security/React/asyncpg/Docker focus, bash restricted to git/grep/cat/ls
- **researcher** — read-only codebase exploration, bash restricted to cat/grep/find/ls/head/tail/wc

---

## Commands (`~/.config/opencode/commands/`)
| Command | Agent | Purpose |
|---------|-------|---------|
| `/deploy` | — | Deploy workflow (details TBD — check file) |
| `/git` | — | Git workflow (details TBD — check file) |
| `/review` | reviewer (subtask) | Review recent changes for bugs/security/style |
| `/status` | researcher (subtask) | Show repo status, recent commits, dirty files |
| `/fix <issue>` | build | Fix a specific issue passed as argument |
| `/prompt <change>` | architect (subtask) | Generate a Cursor prompt for described change |

---

## Snippets (`~/.config/opencode/snippet/`)
| Snippet | Aliases | Purpose |
|---------|---------|---------|
| `#careful` | `#safe` | Read-before-write, step-by-step, ask if ambiguous |
| `#boolab` | `#bl` | BooLab project rules (no useStream.js, check shadcn, CSS vars, asyncpg) |
| `#context` | `#ctx` | Injects project name, branch, recent changes via shell |
| `#nofluff` | `#nf` | Concise mode, commands only |

---

## MCP Servers
| Name | Type | URL | Purpose |
|------|------|-----|---------|
| `context7` | remote | `https://mcp.context7.com/mcp` | Library/framework docs lookup |
| `gh_grep` | remote | `https://mcp.grep.app` | GitHub code search for real-world examples |

---

## Global Rules (`~/.config/opencode/AGENTS.md`)
- Read files before editing. Never write blind.
- One correct command. No broken-then-fix.
- Backup before destructive steps.
- No unsolicited suggestions.
- `pip install --break-system-packages`
- CommonJS default unless project is explicitly ESM.
- `docker compose up --build -d` not restart when env/frontend changes.
- YAML indentation is load-bearing.
- When needing docs, use `context7`. When needing code examples, use `gh_grep`.

---

## Theme
Custom `homelab` theme at `~/.config/opencode/themes/homelab.json`. Burnt orange palette matching BooCode aesthetic — void black background (#0a0600), amber accents (#f5a623), warm text (#ffdcaa), teal variables, green strings, purple numbers. Activated via `~/.config/opencode/tui.json`.

---

## Workflow
1. SSH into homelab via Termius
2. `cd /opt/<project>` (boolab, broccolini-bot, stackctl, dubdrive, etc.)
3. Run `opencode` — plugins auto-load, skills available, agents ready
4. Tab to switch primary agents (build/plan/architect)
5. `@reviewer` or `@researcher` for subagent tasks
6. `/review`, `/status`, `/fix`, `/prompt` for common workflows
7. `#boolab #careful` snippets inline for context injection
8. `/handoff` to create continuation prompt for new session when context fills

---

## Prompt guidelines for qwopus27b
- Explicit step-by-step structure, concise CoT
- Task decomposition with numbered sub-steps
- Tool-call awareness (model is RL-tuned for tool use)
- Avoid prompts that encourage pre-action overthinking — model is tuned for lightweight initial reasoning + execution-driven refinement
- `#boolab` snippet mandatory for any BooLab frontend work
- Always include file-read audit step before edits in Cursor prompts

---

## Known issues
- `opencode-shell-strategy` installed both as npm plugin and local instructions file — npm version takes precedence, local clone in plugins/ is redundant but harmless
- 65K context can fill fast on long sessions — use `/handoff` or session compact mode proactively
- qwopus27b takes ~30s to load if not already in llama-swap — first request may timeout if Bifrost timeout is too low
