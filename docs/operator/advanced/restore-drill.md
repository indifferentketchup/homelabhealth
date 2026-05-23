# Restore drill

This doc covers **verification**, not initial setup. Assume you already have a backrest
repo configured, a forget+prune policy in place, and at least one snapshot. Run through
this drill at least once when first setting up, and at the intervals listed in
[## Schedule](#schedule) below.

**Caveat on commands.** Backrest is primarily HTTP/UI-driven, and the CLI shape varies
by version and deployment. Every `backrest ...` invocation below is pseudo-code — adapt
to your interface (CLI, web UI, or `docker exec` into the backrest container). The
restic-flavored commands shown work in some setups but are not guaranteed to match yours.

## Pre-flight

Confirm the password variable is set (do not expose the value):

```bash
docker exec hlh_api env | grep BACKREST
```

The variable name should appear. If it is missing, stop — your backrest repo password is
not injected into the container.

Confirm the doctor's `backrest_repo` check passes:

```bash
docker exec hlh_api python -m hlh.doctor
```

Look for the `backrest_repo` line. It must show OK before you proceed.

Confirm you have a recent snapshot:

```bash
backrest snapshots
```

If no snapshots exist, create one before drilling a restore.

## Pick a non-production target

Do NOT restore into the live homelabhealth data directory during a drill. Use a scratch
directory:

```bash
mkdir -p /tmp/hlh-restore-drill-$(date +%Y%m%d)
```

## Restore the latest snapshot

```bash
backrest restore latest --target /tmp/hlh-restore-drill-$(date +%Y%m%d)
```

## Verify the contents

- Compare a known file's size or hash between the live path and the restored path.
- Spot-check whether `.env` is present in the restore. If your backrest rules exclude
  `.env` (recommended), it should not appear. If your rules include it, confirm it is
  present and intact.
- If your backup includes a `pg_dump`, load it into a scratch Postgres instance and
  check a representative row count:

```bash
psql -U hlh -d hlh_scratch -c "SELECT COUNT(*) FROM sources;"
```

## Sign-off and cleanup

Write a line in your ops log: date, snapshot ID, what you verified, any issues found.

Delete the scratch directory when done:

```bash
rm -rf /tmp/hlh-restore-drill-$(date +%Y%m%d)
```

If the drill failed: stop. Do not delete the scratch dir until you understand the failure.
File a note in your ops log. Re-attempt after fixing.

## Schedule

- After initial backrest setup.
- After any backrest version upgrade.
- After any host migration.
- Annually at minimum.

Last reviewed: 2026-05-22.
