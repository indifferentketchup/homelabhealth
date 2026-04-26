# BooCode Phase 5.1 — Agentic Spawn (Claude Code / OpenCode in tmux)

**Date**: 2026-04-24
**Status**: Approved (design locked, pending implementation plan)
**Phase**: 5.1 — extends Phase 5 terminal infrastructure
**Author**: brainstormed with Claude Opus 4.7

---

## Overview

Phase 5 shipped BooCode terminals: a `tmux` sidecar container (`boolab_agent`) with per-WebSocket `pty.fork() + tmux attach`, driven from an xterm.js frontend. Today, every session runs `bash -l` inside that container.

Phase 5.1 extends session creation to optionally spawn **Claude Code** (`claude`) or **OpenCode** (`opencode`) CLI agents as the foreground process instead of `bash`. From the user's seat: "new terminal → choose type → bash|claude|opencode". Everything downstream (xterm rendering, send-to-terminal chip, tab bar, save-on-close history) stays unchanged.

Agents run **on the host** via SSH from the agent container, not inside the container. This keeps `boolab_agent` minimal and lets `claude` / `opencode` keep their existing host install, auth state, and config dirs.

## Goals

- Allow users to spawn `claude` or `opencode` as the foreground command of a new terminal session.
- Reuse all existing Phase 5 machinery — xterm.js, tmux session backend, chip/attach flows, save-on-close — without modification.
- Zero tool bind-mounts into the agent container. Zero CC/OC install inside the image.
- Default machine = `ubuntu-homelab` for all session types.

## Non-goals (deferred, NOT part of 5.1)

- ACP (Agent Client Protocol) transport — agents stay as PTY-over-SSH TUIs, not JSON-RPC peers.
- Chat-reads-terminal (Tier 1) or chat-writes-terminal (Tier 2).
- Native tool-use loop inside the BooCode chat LLM.
- Menu grouping at ≥6 open sessions (UX polish).
- Auto-reconnect on SSH drop.
- SSH multiplexing (`ControlMaster`) to amortize handshake cost.
- Multi-host scale-out beyond `ubuntu-homelab`.

## Architecture

```
Browser (xterm.js)
  │   WebSocket: PTY bytes
  ▼
boolab_api (pty.fork + tmux attach -t <uuid>)
  │   tmux protocol over shared socket /shared/tmux/default
  ▼
boolab_agent container   [ tmux server, as UID/GID 1000 ]
  │   tmux window runs:  ssh -t samkintop@<ubuntu-homelab-ip> bash -lc '...'
  ▼
host sshd on ubuntu-homelab (Tailscale IP)
  │   remote PTY on host
  ▼
bash | claude | opencode   [ on host, as UID/GID 1000 samkintop ]
```

The agent container holds only the tmux server plus an SSH client and a read-only key. CC/OC are never installed in the agent container.

## Key design decisions

**Agents run on the host, reached via SSH from the agent container.** They are already installed, authenticated, and version-managed on `ubuntu-homelab`. Running them on the host sidesteps image bloat, version drift inside the container, symlink-chasing (`claude` is an absolute symlink into `/home/samkintop/.local/share/claude/versions/...`), and UID/GID collisions on config dirs.

**Self-loop is an operational fact, not a bug.** The agent container SSHes to the same physical machine it runs on, via that host's Tailscale IP. If host `sshd` is down, *every* SSH-backed terminal breaks simultaneously. This is acceptable: host sshd is already a baseline dependency of the whole box (remote admin, DubDrive, Tailscale SSH). Name it, don't hide it.

**Remote cwd is a host path, not a container path.** The DAW's `repo_path` (e.g., `/HomeLabRepos/myproj`) already resolves on the host — `ubuntu-homelab` *is* the host. SSH carries the literal string to the remote shell; there is no container-to-host path translation. Future contributors must not "normalize" or "map" the cwd through any container-side filesystem view. This is stated in the `target_cmd_for` docstring as a hard invariant.

**`bash -lc` is load-bearing.** The remote command is wrapped as `bash -lc 'cd <cwd> && exec <type>'`. The `-l` forces a **login shell** on the host, which sources `~/.profile` and `~/.bash_profile`. That is where `PATH` is extended to include `~/.local/bin` (where `claude` and `opencode` live) and where `nvm` shims get set up. A non-login SSH shell will not source these and the agent binaries will not be on PATH. **Do not simplify this during review.**

**Three-layer paste pipeline.** Send-to-terminal (from Phase 5's `path:N-M` chip flow) now traverses three PTYs: `tmux load-buffer` → `paste-buffer -d -p` (bracketed paste markers) → `ssh -t` → remote TUI. All three must preserve the `ESC [ 200 ~` … `ESC [ 201 ~` envelope cleanly. Acceptance test #8 covers end-to-end and is a **hard gate**.

**Agent UID/GID match rule.** The bind-mounted SSH key on the host is mode `0600` owned by `samkintop` (UID 1000, GID 1000). SSH will refuse a key file it sees as world/group-readable or owned by a different UID with `UNPROTECTED PRIVATE KEY FILE!` fatal errors. The container's `agent` user MUST be UID 1000 *and* GID 1000. Pin both explicitly in the Dockerfile — do not trust base-image defaults.

---

## Section 1 — Backend

### Schema changes (commit #2)

Add `session_type` column to `terminal_sessions`:

```sql
ALTER TABLE terminal_sessions
  ADD COLUMN IF NOT EXISTS session_type TEXT NOT NULL DEFAULT 'bash'
    CHECK (session_type IN ('bash', 'claude', 'opencode'));
```

**Schema confirmation**: `terminal_machines` already has `host`, `ssh_user`, and `default_cwd` columns (verified at `backend/schema.sql:575-583`). No migrations needed there for Phase 5.1. If a future contributor finds them missing on an older DB, they belong in commit #2.

### `target_cmd_for(machine, session_type, cwd)`

Lives in `backend/services/tmux_session.py`. Returns the argv to hand to `tmux new-session`:

```python
import shlex
from fastapi import HTTPException


def target_cmd_for(machine, session_type: str, cwd: str) -> list[str]:
    """Build argv for `tmux new-session` given (machine, type, cwd).

    INVARIANT: cwd is a HOST path. Passed verbatim to the remote shell via
    SSH. Do NOT translate, normalize, or map through any container view.
    /HomeLabRepos/<repo> is provided on the host via per-repo fstab binds
    (see Section 3 step 0).

    INVARIANT: bash -lc is load-bearing. -l forces a login shell on the
    host so ~/.profile is sourced, extending PATH to include ~/.local/bin
    and ~/.opencode/bin. Do NOT drop -l.

    INVARIANT: ssh -t is required. claude and opencode are full-screen TUIs
    that refuse to start without a remote tty — `-t` forces remote pty
    allocation. Without it the TUI exits immediately with "stdin not a tty".

    INVARIANT: SSH flattens post-host argv with single spaces before sending
    the command to the remote. Therefore `bash -lc <script>` MUST be
    assembled as a SINGLE quoted argv element before being passed to ssh.
    Splitting it as ['bash', '-lc', script] causes the remote shell to
    re-parse `bash -lc cd /path && exec X` as `bash -lc cd` (with $0=path
    discarded → cd to $HOME) chained via && to `exec X` running in the
    outer NON-login shell, bypassing ~/.profile PATH. Local mode (no ssh
    layer) keeps the three-arg form because tmux invokes argv directly.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail='cwd is required')
    if session_type not in ('bash', 'claude', 'opencode'):
        raise HTTPException(status_code=400, detail=f'unknown session_type: {session_type}')

    # Local: tmux invokes argv directly (no ssh, no flatten). Three-arg form is correct.
    if machine.name == 'local':
        if session_type != 'bash':
            raise HTTPException(
                status_code=400,
                detail='claude/opencode require ubuntu-homelab (they run on the host)',
            )
        return ['bash', '-lc', f'cd {shlex.quote(cwd)} && exec bash -l']

    # Remote via SSH. Single-string form to survive ssh's argv flatten.
    target = f'{machine.ssh_user}@{machine.host}'
    ssh = [
        'ssh', '-t',
        '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=3',
        target,
    ]
    if session_type == 'bash':
        remote_script = f'cd {shlex.quote(cwd)} && exec bash -l'
    else:  # claude | opencode
        remote_script = f'cd {shlex.quote(cwd)} && exec {session_type}'
    remote_cmd = f'bash -lc {shlex.quote(remote_script)}'
    return ssh + [remote_cmd]
```

The `-t` forces remote PTY allocation — `claude` and `opencode` are full-screen TUIs and will not render without it. `ServerAliveInterval=30` keeps long agent sessions alive through NAT and idle windows; three missed pings (90s) declare the session dead and SSH exits.

**SSH argv-flatten — third load-bearing invariant.** OpenSSH joins post-host argv with single spaces before sending the command to the remote (`man ssh`: "additional arguments... separated by spaces"). The three-argv form `[..., 'bash', '-lc', script]` arrives at the remote as the shell string `bash -lc <script-words>`, which the remote shell re-splits — `bash -lc` consumes only the next single token as its `-c` script, so `cd /path && exec X` becomes `bash -lc cd` (with `/path` discarded as `$0`, sending cd to `$HOME`) chained via `&&` to `exec X` running in the outer NON-login shell where `.profile`'s PATH additions are absent. Symptom: bash sessions self-corrected because `exec bash -l` re-establishes the login shell (cwd silently wrong but shell alive); agent sessions died with exit 127 because claude/opencode aren't on the non-login PATH. Fix: assemble `bash -lc <shlex.quote(script)>` as ONE argv element before ssh.

### Other backend touchpoints (commit #2)

- `backend/routers/terminals.py` — accept `session_type` in the create-terminal request; persist on the session row; echo back in responses.
- `backend/services/tmux_session.py` — existing `send_keys` pipeline (`tmux load-buffer` + `paste-buffer -d -p`) is unchanged. Bracketed paste markers already flow through; SSH `-t` forwards them transparently.
- No changes to `hooks/useStream.js` or any SSE code — terminals don't use SSE.

### Error handling

| Condition | Status | Message |
|---|---|---|
| Empty `cwd` | 400 | `cwd is required` |
| Unknown `session_type` | 400 | `unknown session_type: <val>` |
| `claude`/`opencode` on `local` | 400 | `claude/opencode require ubuntu-homelab (they run on the host)` |
| `tmux new-session` fails | 500 | bubble stderr from subprocess |
| SSH fails at tmux-window startup | UI observes "client exited" in xterm | Session moves to Recently Closed; no hang |

Keep existing 5-second subprocess timeouts on `tmux_session.py` helpers. Do not add an explicit SSH `ConnectTimeout` — tmux spawn is fire-and-forget.

---

## Section 2 — Frontend

### `NewTerminalModal.jsx` — type picker

Add a three-option "Type" picker between "Machine" and "Label":

```jsx
const [sessionType, setSessionType] = useState('bash')

// ... in render, below the Machine picker, above the Label input:
<div className="flex flex-col gap-1.5">
  <Label>Type</Label>
  <div className="grid grid-cols-3 gap-1.5">
    {[
      { id: 'bash', name: 'Bash', desc: 'Interactive shell' },
      { id: 'claude', name: 'Claude Code', desc: 'Agentic CLI' },
      { id: 'opencode', name: 'OpenCode', desc: 'Agentic CLI' },
    ].map((t) => (
      <button
        key={t.id}
        type="button"
        onClick={() => setSessionType(t.id)}
        aria-pressed={sessionType === t.id}
        className="flex flex-col items-start gap-0.5 rounded border px-2 py-2 text-left transition-colors"
        style={{
          borderColor: sessionType === t.id ? 'var(--orange, #ff8c00)' : 'var(--border)',
          background: sessionType === t.id ? 'var(--bg-card)' : 'transparent',
        }}
      >
        <span className="text-xs font-medium tracking-wide">{t.name}</span>
        <span className="text-[0.6875rem]" style={{ color: 'var(--text-dim)' }}>
          {t.desc}
        </span>
      </button>
    ))}
  </div>
</div>
```

Pass `sessionType` through the create request:

```jsx
await terminalsApi.create({
  machineId,
  sessionType,
  dawId: attachToDaw ? dawId : null,
  label: label.trim() || null,
  startingCmd: startingCmd.trim() || null,
  cwd: cwdOverride,
})
```

### Default machine

`ubuntu-homelab` stays the default for **all** types. The existing default-picker effect (`NewTerminalModal.jsx:57-65`) already prefers `ubuntu-homelab`. After commit #1's schema flip enables it as an SSH target, no picker logic changes.

### Auto-label

When `label` is blank at submit time, frontend fills `{type}-{n}` where `n` is the next integer that keeps the label unique within the DAW. E.g., third blank-label `claude` on DAW `X` becomes `claude-3`. If the user explicitly cleared the field, respect blank — only auto-fill when it starts blank and the user hasn't touched it.

### Modal progress states

SSH connect + agent boot can take 1–2 s. Extend the submit button label:

- `submitting=false` → `START`
- `submitting=true`, elapsed < 500 ms → `STARTING…`
- `submitting=true`, elapsed ≥ 500 ms, `sessionType !== 'bash'` → `CONNECTING…`

### No changes to

- Tab bar (`TerminalTabBar.jsx`) — tabs show the label, not the type.
- Send-to-terminal right-click menu.
- ⌘K command palette.
- Save-on-close history — terminals-by-type are written the same way.

---

## Section 3 — Infrastructure / Docker

### `Dockerfile.agent` (commit #1)

Diff from current state at `backend/Dockerfile.agent`:

```dockerfile
FROM debian:bookworm-slim

# (existing apt install line — openssh-client is already present, keep it)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux openssh-client bash ca-certificates \
    git curl wget jq less file tree rsync unzip zip \
    vim nano sudo procps iproute2 man-db \
    python3 python3-pip python3-venv \
    nodejs npm \
    make build-essential \
    && rm -rf /var/lib/apt/lists/*

# CHANGED: pin UID *and* GID explicitly to 1000 (match host samkintop).
# Base-image default useradd behavior is not a contract; SSH key file mode
# 0600 means only UID 1000 can read it.
RUN groupadd --gid 1000 agent \
 && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash agent \
 && echo 'agent ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agent \
 && chmod 0440 /etc/sudoers.d/agent \
 && install -d -m 0700 -o agent -g agent /home/agent/.ssh
#  ^^^^ NEW: pre-create .ssh with 0700 + agent ownership *before* any bind
#  mount attaches. Docker bind-mounts do not reset directory mode/ownership
#  on the mount point; a missing or wrong-mode parent breaks SSH with
#  "Bad owner or permissions" at key read time.

COPY tmux.conf /home/agent/.tmux.conf
RUN chown agent:agent /home/agent/.tmux.conf

COPY tmux-agent-entrypoint.sh /usr/local/bin/tmux-agent-entrypoint.sh
RUN chmod +x /usr/local/bin/tmux-agent-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/tmux-agent-entrypoint.sh"]
```

Net diff:
- `+ groupadd --gid 1000 agent` (explicit GID pin)
- `useradd -m -u 1000` → `useradd --uid 1000 --gid 1000 --create-home` (use the pinned group)
- `+ install -d -m 0700 -o agent -g agent /home/agent/.ssh`
- No tool install (no `npm i -g claude-code`, no opencode binary, no PATH edits for bind-mounted bins).

### `docker-compose.yml` — `boolab_agent` service (commit #1)

Current state (lines 21–35) bind-mounts the entire `.ssh` directory read-only. For Phase 5.1 we narrow to two specific files:

```yaml
services:
  boolab_agent:
    # ... unchanged build/container_name/restart
    volumes:
      - boolab_tmux:/shared/tmux
      # REMOVED: - /home/samkintop/.ssh:/home/agent/.ssh:ro  (full dir)
      # ADDED: narrow surface to only the files SSH actually needs
      - /home/samkintop/.ssh/id_ed25519:/home/agent/.ssh/id_ed25519:ro
      - /home/samkintop/.ssh/known_hosts:/home/agent/.ssh/known_hosts:ro
      # DubDrive repo root — unchanged
      - /docker/dubdrive/files/samkintop/HomeLabRepos:/HomeLabRepos:rw
    networks:
      - boolab_net
```

Mirror the same changes in `docker-compose.core.yml`.

**Why narrow**: the whole-directory mount currently exposes `authorized_keys`, `config`, `id_ed25519.pub`, any additional private keys, and anything else under `~samkintop/.ssh`. The agent container only needs its own identity (`id_ed25519`) and the pre-validated `known_hosts` entry for ubuntu-homelab. Smaller surface is strictly better.

### Schema flip (commit #1)

Two edits in `backend/schema.sql`, both idempotent via `apply_schema()` at API boot:

**Seed INSERT** (schema.sql:612-617) — change the ubuntu-homelab row:

```sql
INSERT INTO terminal_machines (name, host, ssh_user, default_cwd, enabled) VALUES
    ('local',          'localhost',        NULL,         '/opt',           FALSE),
    ('ubuntu-homelab', '100.114.205.53',   'samkintop',  '/HomeLabRepos',  TRUE),
    ('sam-desktop',    '100.101.41.16',    'samki',      NULL,             TRUE),
    ('embedding',      '100.90.172.55',    'samkintop',  NULL,             FALSE)
ON CONFLICT (name) DO NOTHING;
```

> **Confirm the IP**: `100.114.205.53` is the Tailscale IP captured in the brainstorming session; verify against `tailscale ip` on the host before committing.

**Idempotent repair UPDATE** (schema.sql:625-633) — reverses direction. The existing UPDATE forces ubuntu-homelab back to local bash on every startup; replace it with an update that forces it TO the SSH target:

```sql
-- ubuntu-homelab is now an SSH target to the host itself. Repair legacy DBs
-- on every API restart — previous incarnation stored host='localhost' +
-- ssh_user=NULL (see Phase 5 Session 2 notes). This UPDATE replaces that one.
UPDATE terminal_machines
   SET host = '100.114.205.53',
       ssh_user = 'samkintop',
       default_cwd = '/HomeLabRepos',
       enabled = TRUE
 WHERE name = 'ubuntu-homelab';
```

The `local` disable UPDATE (schema.sql:621-623) is unchanged.

### One-time host bootstrap (deploy runbook, not code)

0. **Host `/HomeLabRepos/<repo>` per-repo bind mounts.** The Phase 5 `boolab_agent` container resolves `/HomeLabRepos/<repo>` via a single compose-level bind mount of `/docker/dubdrive/files/samkintop/HomeLabRepos`. The Phase 5.1 SSH path runs `cd /HomeLabRepos/<repo>` *on the host*, which sees those paths only if each repo has its own bind mount in `/etc/fstab`. The 13 binds must mirror DubDrive's mount table (the source of truth for repo casing and the `bourbites→bourbites3` alias). Generate them from `docker inspect dubdrive` rather than typing by hand:

   ```bash
   docker inspect dubdrive --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' \
     | awk -F' -> ' '$2 ~ /^\/data\/files\/samkintop\/HomeLabRepos\// {
         sub(/^\/data\/files\/samkintop\/HomeLabRepos\//, "/HomeLabRepos/", $2)
         printf "%s %s none bind 0 0\n", $1, $2
       }' \
     | sort > /tmp/homelabrepos-fstab.lines
   ```

   Pre-create the 13 child mountpoint directories under `/HomeLabRepos` (Linux bind mounts require existing targets):

   ```bash
   awk '{print $2}' /tmp/homelabrepos-fstab.lines | sudo xargs mkdir -p
   ```

   Backup `/etc/fstab`, append the lines, and apply:

   ```bash
   sudo cp /etc/fstab /etc/fstab.bak-$(date +%Y%m%d)
   {
     echo ""
     echo "# BooCode Phase 5.1 — /HomeLabRepos visibility on host (mirrors dubdrive container binds)"
     cat /tmp/homelabrepos-fstab.lines
   } | sudo tee -a /etc/fstab > /dev/null
   sudo mount -a
   ```

   Verify each child is a mountpoint and content sanity-checks pass:

   ```bash
   while read -r src tgt rest; do
     printf "%-40s " "$tgt"; mountpoint -q "$tgt" && echo OK || echo FAIL
   done < /tmp/homelabrepos-fstab.lines
   ls /HomeLabRepos/boolab/.git | head -3
   ```

   Without these binds, agent TUIs exit immediately with `cd: /HomeLabRepos/<repo>: No such file or directory`. New DAWs require a corresponding fstab entry — see the Risks table below.

1. **Self-SSH auth**: ensure the host's own public key is in its authorized_keys:
   ```
   cat ~samkintop/.ssh/id_ed25519.pub >> ~samkintop/.ssh/authorized_keys
   # (skip if already present; sort -u to dedupe)
   ```

   **1.5. Login-shell PATH for agent binaries.** `bash -lc` (the shell `target_cmd_for` invokes on the remote) sources `~/.profile` / `~/.bash_profile` — NOT `~/.bashrc`. Tool installers that only edit `.bashrc` (default OpenCode install) will not be on PATH for the SSH-from-container path; the agent TUI exits 127 immediately. Verify both binaries via the exact login-shell environment:

   ```bash
   ssh samkintop@<host> 'bash -lc "command -v claude && command -v opencode"'
   ```

   If either is missing, append the install dir to `~/.profile` (idempotent):

   ```bash
   ssh samkintop@<host> 'grep -qF "/path/to/dir" ~/.profile || \
     echo "export PATH=\"\$HOME/.opencode/bin:\$PATH\"" >> ~/.profile'
   ```

   (For the canonical install, the OpenCode binary lives at `~/.opencode/bin/opencode` — adjust if your installer differs.)

2. **known_hosts pre-populate**: prevent the first-connection TOFU prompt (required by `StrictHostKeyChecking=yes`):
   ```
   ssh-keyscan 100.114.205.53 >> ~samkintop/.ssh/known_hosts
   # (skip if already present)
   ```
3. **Verify from container**:
   ```
   docker exec -it boolab_agent ssh samkintop@100.114.205.53 'hostname && pwd'
   ```
   Must succeed without prompts. If it asks for a password: step 1 missed. If it fails with `Host key verification failed`: step 2 missed.

---

## Section 4 — Rollout, Testing, Commits

### Commit #1 — structural only (no user-visible behavior change)

- `backend/Dockerfile.agent` — add `groupadd --gid 1000`; change `useradd` to pin UID *and* GID explicitly; add `install -d -m 0700 -o agent -g agent /home/agent/.ssh`
- `docker-compose.yml` — narrow `.ssh` bind mount from whole-dir to two files (`id_ed25519`, `known_hosts`)
- `docker-compose.core.yml` — same narrowed mounts
- `backend/schema.sql` — flip ubuntu-homelab seed and idempotent UPDATE to SSH target
- One-time host bootstrap (authorized_keys + known_hosts) per deploy runbook above
- No backend logic changes, no frontend changes

Post-deploy verification: `docker exec -it boolab_agent ssh samkintop@100.114.205.53 'hostname'` must succeed. Existing bash terminals via `ubuntu-homelab` now run on the host (user-visible: `hostname` reports the host, not the container) — acceptable and in fact correct.

### Commit #2 — wires up agent types

- `backend/schema.sql` — `session_type` column on `terminal_sessions` (migration via `apply_schema()`)
- `backend/routers/terminals.py` — accept and persist `session_type` on create; echo in responses
- `backend/services/tmux_session.py` — new `target_cmd_for(machine, session_type, cwd)` as specified in Section 1
- `frontend/src/api/terminals.js` — pass `sessionType` through to the create request
- `frontend/src/pages/boocode/NewTerminalModal.jsx` — type picker, auto-label counter, extended progress states
- No dep additions

### Acceptance tests

All run against the live stack (no mocks, per project feedback memory):

1. **Bash default** — new terminal, default type (`bash`), default machine (`ubuntu-homelab`), DAW with `repo_path=/HomeLabRepos/<repo>`. Run `hostname && pwd && whoami && ls .git/HEAD`. Pass: hostname is the host (not container), **pwd matches the DAW's `repo_path`** (regression guard against ssh-flatten cd-discard), whoami=samkintop, `.git/HEAD` exists.
2. **Bash local** — new terminal, `type=bash`, `machine=local`. Verify: prompt in agent container (`whoami` → `agent`, `hostname` → container ID).
3. **Claude spawn** — new terminal, `type=claude`, `machine=ubuntu-homelab`. Verify: `claude` TUI renders; its initial screen is visible and interactive.
4. **OpenCode spawn** — new terminal, `type=opencode`, `machine=ubuntu-homelab`. Verify: `opencode` TUI renders.
5. **Claude on local rejected** — create with `type=claude`, `machine=local`. Verify: 400 with `claude/opencode require ubuntu-homelab (they run on the host)`.
6. **cwd required** — create with empty `cwd`. Verify: 400 with `cwd is required`.
7. **Auto-label uniqueness** — create three blank-label `claude` terminals on one DAW. Verify: labels `claude-1`, `claude-2`, `claude-3`.
8. **Bracketed paste through SSH → agent TUI** *(HARD GATE)* — open a claude session; in `RepoFilePreview` select a multi-line snippet containing backticks, `$VAR`, double-quotes, and embedded newlines; send via the path:N-M chip. Verify: the remote TUI receives the block as a single bracketed paste. Specifically:
   - No `$VAR` shell expansion
   - No backtick command substitution
   - No interpretation of embedded quotes
   - Newlines preserved
   - The TUI's paste indicator (where applicable) activates
9. **Save-on-close** — start a claude session, interact briefly, close the tab via Save & Close. Verify: history file at `/opt/boolab/history/<daw-slug>/terminals/<timestamp>-<label>.txt` exists, ANSI stripped, content readable.
10. **SSH drop** — start a claude session; momentarily stop host `sshd` (e.g., `systemctl stop ssh`; restart it after ~5s). Verify: tmux window shows `Connection to 100.114.205.53 closed.` or `client_loop: send disconnect`; session appears in Recently Closed; no hang in xterm; no zombie PTY on the API side.

### Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Host `sshd` down → every SSH-backed terminal breaks simultaneously | High (blocks all ubuntu-homelab terminals; `local`/bash still works) | Operational fact, not a bug. Host sshd is a baseline dependency. Existing uptime checks cover it. |
| SSH session death is not auto-reconnected | Medium (user loses TUI state on network blip or host sshd restart) | Documented in user-facing help text. Operator kills the dead tmux window and respawns. `ServerAliveInterval=30` + `ServerAliveCountMax=3` reduces false drops (90s grace). No code for MVP. |
| sshd `MaxSessions` default is 10 | Low today (single owner, rarely ≥10 concurrent); becomes real at 11+ | Not blocking for MVP. If hit: edit `/etc/ssh/sshd_config` → `MaxSessions 30`, then `systemctl reload ssh`. Add to deploy runbook. |
| Three-layer paste regression (tmux → ssh -t → remote TUI) | Medium (breaks chip send-to-terminal for agent sessions) | Acceptance test #8 is a hard gate on every change to `tmux_session.py` or `target_cmd_for`. |
| Container UID/GID drift from 1000 | High (SSH refuses key with UNPROTECTED PRIVATE KEY) | Dockerfile pins both explicitly. CI (if ever added) can assert `id agent` inside the image prints `uid=1000(agent) gid=1000(agent)`. |
| Agent `.ssh` dir permissions wrong at runtime (missing pre-create) | High (SSH refuses key) | Dockerfile pre-creates `/home/agent/.ssh` mode 0700 owned by agent *before* the bind mount attaches. Bind-mounted files inherit host mode (0600 for key). |
| Narrowed bind mount breaks a future code path | Low | Only `id_ed25519` and `known_hosts` are needed for our SSH calls. If a future consumer needs the wider `.ssh` (e.g., a new host's `authorized_keys` read), they can add a specific mount in their own change. |
| CC/OC version drift on host | Low | Agents update via host's normal channels (nvm, npm, etc.). Container doesn't pin any version because the container doesn't see them. Spec's run-on-host decision specifically avoids this class of problem. |
| Self-loop SSH latency | Negligible (<1 ms over lo + Tailscale NAT) | — |
| Tool installer edits only `.bashrc` → invisible to `bash -lc` | High (agent TUI exits 127 immediately on spawn) | Bootstrap step 1.5 verifies via login shell. Add export to `.profile` if either binary missing. |
| New DAW added without a paired `/HomeLabRepos/<repo>` fstab entry | Medium (agent TUI fails for that DAW only; regression silent until first agent spawn) | Operator runbook: every DAW with a `repo_path` needs a fstab line + `mount -a`. Future improvement: a generator script that reads dubdrive's live mount table and emits diff. |
| SSH argv-flatten breaks three-arg `bash -lc <script>` form | High (silent cwd bug for bash; immediate exit 127 for claude/opencode) | `target_cmd_for` assembles bash invocation as a single shlex-quoted argv element. Local mode keeps three-arg form. Acceptance Test 1's `pwd` check + Test 3's liveness check guard against regression. |

### Deferred (do not build in 5.1)

- ACP transport for Claude / OpenCode
- Native tool-use loop for the BooCode chat LLM
- Chat ↔ terminal cross-awareness (Tier 1 / Tier 2)
- Menu grouping by type at ≥ 6 sessions
- Auto-reconnect on SSH drop
- ControlMaster multiplexing to amortize per-session SSH handshake
- Multi-host support (N > 1 remote machines for agent types)
- De-rooting `boolab_api` (orthogonal operational cleanup)

---

## Appendix A — Why not the alternatives?

**Why not install `claude`/`opencode` inside the agent container?** Version drift (host nvm updates wouldn't propagate), symlink chasing (`claude` binary is an absolute symlink into `~samkintop/.local/share/claude/versions/...`), auth state duplication (agents store tokens in `~/.claude/`, `~/.config/opencode/`), and image bloat. Running on the host keeps one source of truth.

**Why not bind-mount the tool directories into the container?** Considered at length (Path 1, then Path A with selective mounts). Dropped because (a) absolute symlinks in `~/.local/bin` point to paths that don't exist inside the container without matching `~/.local/share` mounts, (b) UID alignment becomes load-bearing in more places, and (c) host-side upgrades risk racing with container-side reads. SSH-to-host removes all of this.

**Why not use ACP (Agent Client Protocol)?** ACP would let us speak JSON-RPC to CC/OC instead of driving PTYs. Genuinely better long-term but a bigger lift: new backend protocol adapter, new frontend rendering (not an xterm), and both agents' ACP servers are still evolving. 5.1 is a PTY-only MVP. ACP is explicitly listed in "Deferred".

**Why not a tool-use loop in the BooCode chat LLM?** That's a product pivot (BooCode chat becomes an agent), not a feature extension. Out of scope.

**Why per-repo fstab binds instead of a single `/HomeLabRepos` bind?** The repos don't live under one host parent. DubDrive composes them from 13 separate `/opt/<repo>` working dirs (some lowercase, some not, plus `bourbites→bourbites3` aliasing). A single parent bind would only work if `/opt` itself were the source — which would expose every other `/opt/<service>` (caddyui, dubdrive, monitoring, etc.) under `/HomeLabRepos`, not just the DAW-relevant repos. Per-repo binds keep the surface narrow and the casing exact. The `bourbites3→bourbites` alias is the trap: DubDrive's UI strips the version suffix; hand-typing fstab would silently miss it. Use `docker inspect dubdrive` as the source of truth.

## Appendix B — Where this spec is served

This document is committed at `docs/superpowers/specs/2026-04-24-boocode-phase-5.1-agentic-spawn-design.md` and mirrored at `frontend/public/spec.md` so the BooCode UI can serve a rendered copy at `https://boocode.indifferentketchup.com/spec`. The React route lives in `ModeRouter.jsx` (boocode branch) and renders via `react-markdown` + `remark-gfm`.

The two copies are kept in sync manually. When editing, update both. A future improvement would replace the copy with a Vite `?raw` import from the `docs/` path, but that requires relaxing `server.fs.allow` and is not in this spec's scope.
