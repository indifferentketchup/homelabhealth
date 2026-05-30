# Breach Response Playbook

Operator playbook for a suspected compromise of the homelabhealth stack. Not a SOC runbook.

---

## Step 0: Decide if this is a breach

Investigate before acting. Signals worth taking seriously:

Unexpected outbound traffic from the host (check via `ss -tnp` or host-level firewall logs).
Unfamiliar processes visible inside containers (`docker top hlh_api`, `docker top hlh_db`).
Unexpected modifications to `bundled_models` or `providers` rows in the database: bundled rows
should never change without an explicit `docker compose up --build`. Unexpected rows in
`source_chunks` when C5 has not shipped: this table must stay empty until v0.17.0. Doctor
pre-flight checks (`python -m hlh.doctor`) turning red on checks that were green at the last
run, with no corresponding code change.

If in doubt, treat it as a breach and proceed to Step 1.

---

## Step 1: Isolate the host

Stop the stack without removing volumes or network state: you want those intact for forensics:

```bash
docker compose -f /opt/homelabhealth/docker-compose.yml stop
```

Use `stop`, not `down`. Volumes and network interfaces survive `stop`; `down` removes them,
destroying forensic state.

If you suspect credential compromise (VPN key, SSH key, or similar), disconnect
from your network overlay before proceeding.

Do not reboot the host until you have completed Step 2.

---

## Step 2: Snapshot evidence before changing anything

Capture container logs and inspect data before any rotation, rebuild, or restart:

```bash
docker compose logs --no-color > /tmp/hlh-incident-$(date +%Y%m%d-%H%M%S)-compose.log
```

```bash
docker inspect hlh_api hlh_chat hlh_orchestra hlh_search hlh_ui hlh_db \
  > /tmp/hlh-incident-$(date +%Y%m%d-%H%M%S)-inspect.json
```

Dump the database to an offline, encrypted location:

```bash
pg_dump -U hlh -d hlh > /tmp/hlh-incident-$(date +%Y%m%d-%H%M%S)-db.sql
```

Encrypt the dump immediately before moving it off the host (gpg, age, or LUKS-encrypted volume).

Take a host syslog snapshot (`/var/log/syslog` or `journalctl -a` output).

Note the current commit SHA and tag of the running deployment:

```bash
git -C /opt/homelabhealth rev-parse HEAD
git -C /opt/homelabhealth describe --tags
```

---

## Step 3: Rotate keys

Rotate in dependency order: least-coupled first. Swapping a key while dependents still hold
the old key causes service failures; follow this order.

**1. HF_TOKEN.** Revoke the existing token at huggingface.co/settings/tokens. Generate a new
one with the minimum required permissions (read access to the specific model repos). Re-enter it
via Settings → System → HF Token in the UI, or directly in the database:

```sql
UPDATE hf_token_config SET token = '<new-encrypted-token>' WHERE id = (SELECT id FROM hf_token_config LIMIT 1);
```

If using the UI, the token is Fernet-encrypted automatically by the API.

**2. Provider API keys.** For every non-bundled provider row in `providers`, revoke the key at
the upstream provider (OpenAI, Anthropic, or whoever), generate a new one, and re-enter it via
Settings → Providers in the UI. Do not update the database directly unless the API is unavailable.

**3. PROVIDER_KEY_ENCRYPTION_KEY.** Generate a new Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Before swapping the env var, re-encrypt all existing encrypted rows using the new key. Swapping
the env var without re-encryption bricks all stored secrets: the API cannot decrypt them with
the new key. If you cannot re-encrypt safely, wipe the `providers` table and re-enter all keys
after bringing the stack back up with the new key.

**4. LUKS passphrase on the host disk.** If the compromise reached disk-level access, rotate the
LUKS passphrase (`cryptsetup luksChangeKey`). This requires having a slot available; confirm
your slot count before proceeding (`cryptsetup luksDump`).

**5. Backrest repo passphrase.** If backups may have been accessed or if the passphrase was
co-located with the LUKS key, rotate the backrest repo passphrase and re-seal the repo.

**6. Reverse-proxy auth credentials.** Rotate any reverse-proxy secrets (oauth2-proxy cookie
secrets, nginx basic auth passwords, etc.) as appropriate for your setup. These are operator-owned
and not managed by homelabhealth.

---

## Step 4: Notify

**Single-operator deployment:** no third party requires notification. Record the incident for
personal records (see Step 5).

**Multi-user deployment:** notify all affected users in writing. State what was exposed,
when, what was rotated, and what they should do (re-enter provider keys, regenerate any
shared credentials). Do this within 72 hours of identifying the breach.

---

## Step 5: Document the timeline

Write a plain-text incident file:

```
/opt/homelabhealth/incidents/YYYY-MM-DD-<slug>.md
```

Include:

- Detection time (YYYY-MM-DD HH:MM local + timezone)
- Isolation time
- Evidence snapshot file locations
- List of rotated keys and rotation timestamps
- Notified parties and notification timestamps
- Root cause (if determined)
- Fix or patch landed (commit SHA or tag)

Commit this file to a separate private repository. Do not commit it to the homelabhealth
repository: it may reference credential rotation details or personal information.

---

## Step 6: Recover

Restore from the most recent pre-incident backrest snapshot if data integrity is in doubt.
Verify the snapshot's timestamp against the incident timeline before restoring.

Pull the current tag fresh from the repository:

```bash
git -C /opt/homelabhealth fetch
git -C /opt/homelabhealth checkout v<tag>
```

Re-run the doctor check before bringing the stack back up:

```bash
docker exec hlh_api python -m hlh.doctor
```

If the API container is not running yet, run the doctor after the initial `up`:

```bash
docker compose up -d
docker exec hlh_api python -m hlh.doctor
```

Re-enter all rotated secrets via the UI or environment. Confirm the doctor exits 0 (all green).

Monitor container logs for 24 hours after recovery:

```bash
docker logs -f hlh_api
```

Watch for unexpected outbound connections, repeated 403s on bundled provider rows, or error
patterns that were not present before the incident.
