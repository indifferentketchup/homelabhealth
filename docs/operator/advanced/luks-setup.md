# LUKS setup for the data volume

LUKS encryption protects data at rest when the host disk is physically removed or
stolen. It does NOT protect against a live attacker who already has root on the running
host — once the volume is unlocked and mounted, the OS reads it in cleartext.

## One-time. Before HLH install.

**Do this BEFORE installing homelabhealth. Do this BEFORE creating any docker volumes
that will hold homelabhealth data.** If data already exists on an unencrypted volume,
you must migrate it off first. That migration is not covered here.

## Identify the target device

```bash
lsblk
```

Example output:

```
NAME   MAJ:MIN RM   SIZE RO TYPE MOUNTPOINT
sda      8:0    0   120G  0 disk
└─sda1   8:1    0   120G  0 part /
sdb      8:16   0   500G  0 disk
```

Pick the device you intend to encrypt (e.g., `/dev/sdb`). Do NOT pick a device that
holds existing data you have not migrated off.

## Create the LUKS volume

```bash
sudo cryptsetup luksFormat /dev/<target>
```

This destroys all data on the device. Type `YES` (literal upper-case) to confirm.
Set a strong passphrase and save it in your password manager — see
[./key-custody.md](./key-custody.md) for storage guidance.

## Open and format

```bash
sudo cryptsetup open /dev/<target> hlh-data
sudo mkfs.ext4 /dev/mapper/hlh-data
```

## Mount and persist

```bash
sudo mkdir -p /var/lib/homelabhealth
sudo mount /dev/mapper/hlh-data /var/lib/homelabhealth
```

## Auto-mount at boot via /etc/crypttab

Get the LUKS UUID:

```bash
sudo blkid /dev/<target>
```

Add to `/etc/crypttab` (one line):

```
hlh-data  UUID=<luks-uuid>  none  luks
```

Add to `/etc/fstab` (one line):

```
/dev/mapper/hlh-data  /var/lib/homelabhealth  ext4  defaults  0  2
```

`none` in crypttab means the OS will prompt for the passphrase at each boot. For
unattended unlock, use a key file — see your distro's cryptsetup documentation.

## Verify with the doctor

After bringing the stack up:

```bash
docker exec hlh_api python -m hlh.doctor
```

Look at the `luks_status` row. The check shells out to `docker info`, `df`, and `lsblk`
and is best-effort from inside the container. In most default configs it returns WARN
with `"luks status unverifiable from container — confirm manually per docs/operator/advanced/luks-setup.md"`.
If the container has host visibility into block devices, the check may return OK
(`dm-crypt detected on ...`) or WARN (`data volume is not on LUKS`). Treat any WARN
containing "is not on LUKS" as a real issue — that is the check positively reporting an
unencrypted data volume, not a visibility limitation. Whatever the doctor reports,
confirm manually on the host:

```bash
lsblk -f
```

The `/dev/mapper/hlh-data` entry should appear with `crypto_LUKS` in the tree above it.

## What this does not cover

- Migrating existing unencrypted data onto a fresh LUKS volume.
- LUKS2 vs LUKS1 (`cryptsetup luksFormat` defaults to LUKS2; prefer that).
- Key-file-based unlock (see `man cryptsetup`).
- Header backup (recommended; see `cryptsetup luksHeaderBackup`).

Last reviewed: 2026-05-22.
