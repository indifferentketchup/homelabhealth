# Key custody

This doc covers two operator-generated secrets used by homelabhealth: `HLH_MASTER_KEY`
(the column-encryption key, consumed by the C6 layer shipping at v0.18.0) and
`BACKREST_REPO_PASSWORD` (the backrest repo passphrase). Both must be generated on the
operator's own host. They must not be generated anywhere else.

## Generate on your host. Not on the maintainer's.

If the maintainer generates them, the maintainer has copies — which defeats the C6 threat
model entirely. The maintainer cannot help you recover these secrets, and does not want to
see them.

- Generate these on your machine.
- Do not let anyone else generate them for you.
- Do not paste them into a chat with the maintainer.

## Generating HLH_MASTER_KEY

The `HLH_MASTER_KEY` is validated today by the doctor's `master_key` check and will be
used by the C6 column-encryption layer at v0.18.0. Generate at least 32 characters of
random base64:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the output into your `.env` file (or a docker secret) as:

```
HLH_MASTER_KEY=<value>
```

## Generating BACKREST_REPO_PASSWORD

Option 1 — CLI:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Option 2 — use your password manager's random-character generator (24+ characters,
no special characters that your shell might interpret).

Paste the result as `BACKREST_REPO_PASSWORD=<value>` in `.env`, or place in
`/run/secrets/backrest_password` if you use docker secrets (you wire the secrets stanza
in `docker-compose.yml` yourself).

## Where they live

- `.env` at the repo root — preferred for solo operators.
- `/run/secrets/backrest_password` — if using docker secrets.
- **Never** in the database.
- **Never** in a frontend config file.
- **Never** in git.
- **Never** in a chat log.

## Backups of these keys

- Write them on paper; store in a physically secure location.
- Save in an offline password manager (KeePassXC, 1Password, Bitwarden local vault, etc.).
- If you lose `HLH_MASTER_KEY` after v0.18.0/C6 ships and encrypted rows exist, those
  rows are unrecoverable. There is no "forgot password" path.
- If you lose `BACKREST_REPO_PASSWORD`, your backups are unrecoverable. Same deal.

## What NOT to do

- Do NOT generate these on a shared, remote, or borrowed machine.
- Do NOT copy them via a clipboard-sync service that touches a cloud server.
- Do NOT paste them into a chat with the maintainer or anyone else.
- Do NOT use placeholder strings (`changeme`, `password`, `example`, etc.) — the doctor
  check fails on those.
- Do NOT commit them to git. Add `.env` to `.gitignore` if it is not already there.

Last reviewed: 2026-05-22.
