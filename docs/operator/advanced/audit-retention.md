# Audit log retention

## Status

Audit log retention is opt-in. The default keeps every row forever.
Set `HLH_AUDIT_LOG_RETENTION_DAYS` when your storage budget or forensic
policy requires a bounded window. Rows outside the window are deleted
permanently — there is no soft-delete or archive step.

## Setting the env var

In `.env` (persists across container restarts and rebuilds):

```
HLH_AUDIT_LOG_RETENTION_DAYS=365
```

Common values: `90` (90 days), `365` (one year), `730` (two years).
Leave the variable unset to keep all rows indefinitely.

## Running the prune

Always do a dry-run first to confirm the row count before deleting:

```bash
docker exec hlh_api python -m hlh.audit_retention --dry-run
```

If the count looks correct, prune for real:

```bash
docker exec hlh_api python -m hlh.audit_retention
```

The command exits 0 on success or no-op. On DB error it exits 1 and
prints to stderr.

## Cron schedule (host crontab)

Run weekly, early Sunday morning. Edit with `crontab -e`:

```cron
# Prune audit log — weekly, 03:00 Sunday
0 3 * * 0 docker exec hlh_api python -m hlh.audit_retention >> /var/log/hlh-audit-retention.log 2>&1
```

Redirect stdout to a log file so you have a record of each prune run.

## Chain integrity after a prune

The hash chain remains valid from the new oldest row backward to itself.
Deleted rows are gone permanently; the chain cannot be reconstructed from
the remaining rows alone.

This is intentional: a retention prune is a deliberate operator action,
not a forensic event. The `doctor` check (`audit_log_chain`) validates
all remaining rows each time it runs. If you need to verify the chain
covered a deleted range, you need a backup that pre-dates the prune.

Note: `verify_chain --since` (to skip rows before a known cutoff) is not
yet implemented. The current doctor check reads all remaining rows.

## Recovery if you mis-pruned

Pruned rows cannot be recovered from the live database. Restore from a
backrest snapshot that predates the prune. See
[./restore-drill.md](./restore-drill.md) for the restore procedure.

Last reviewed: 2026-05-23.
