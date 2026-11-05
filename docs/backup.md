# Backing up result bundles

Result bundles live in a local `results` folder by default. `meridian backup` copies
completed bundles to an Azure Blob Storage container, so results survive a lost or
replaced laptop and colleagues with access to the container can retrieve them.

```bash
export MERIDIAN_BACKUP_SAS_URL='https://<account>.blob.core.windows.net/?sv=...&sig=...'
python -m meridian backup --output results
```

## Access

The command authenticates with a **shared access signature (SAS) URL** read from the
`MERIDIAN_BACKUP_SAS_URL` environment variable. Nothing is stored in settings files or
the repository.

Create an account-level SAS in the Azure portal (Storage account > Shared access
signature) or with the Azure CLI, with:

| Setting | Value |
|---|---|
| Allowed services | Blob |
| Allowed resource types | Container, Object |
| Permissions | Read, Write, List |
| Expiry | As short as practical, e.g. 30 days |
| Allowed protocols | HTTPS only |

Treat the SAS URL like a password: anyone holding it can write to the account until it
expires. Rotate it by generating a new one and updating the environment variable.

## What is uploaded

- Only **completed** bundles (folders with `COMPLETE.json`) are uploaded.
- Each bundle is **verified** first (manifest and file hashes). A bundle that fails
  verification is skipped and named in the output, so one damaged bundle does not stop
  the rest.
- Every file in the bundle is uploaded as `<container>/<bundle folder>/<file name>`, with
  a content type matching its extension.
- Files larger than 256 MB are refused.

## Choosing bundles

By default every completed bundle in the results folder is uploaded. Add `--bundle` (once
per bundle) to upload only named bundle folders, for example the run you are about to
share:

```bash
python -m meridian backup --output results --bundle baseline-0123456789ab
```

An unknown or incomplete bundle name stops the command before anything is uploaded.

## Dry run

`--dry-run` verifies the bundles and reports how many files would be uploaded, without
contacting Azure or needing the SAS URL.

## Errors

| Situation | Behaviour |
|---|---|
| `MERIDIAN_BACKUP_SAS_URL` not set or malformed | Stops with an explanation before uploading anything |
| Storage unreachable (network error) | Stops with "Cannot reach blob storage" |
| Upload rejected (HTTP 400, 404, 409, 413) | Stops and names the file |
| Temporary server error | The upload is retried |
| Bundle fails verification | Skipped and listed; the backup continues |

Each request has a 30-second timeout.

## Restoring

Download a bundle's files from the container into a folder in your results directory,
then check it with `compare` or `dashboard`, which verify the manifest and hashes before
using a bundle. A bundle restored incompletely fails verification rather than giving
wrong results.

## Listing and restoring

```bash
python -m meridian backup --list
python -m meridian restore baseline-0123456789ab --output results
```

`backup --list` prints the bundles already in the container. `restore` downloads one
bundle: it reads the bundle's `COMPLETE.json` from the container, downloads every file it
lists, writes them to a new folder under `--output` and verifies the result. It refuses to
overwrite an existing folder. A bundle that fails verification after download (for
example because a file in the container was changed) is reported and should not be used.

## Backup log

Every backup run (not dry runs) appends an entry to `backup_log.json` in the results
folder: when it finished, which bundles and how many files and bytes were uploaded, and
which bundles were skipped. The log stays local; it is not uploaded.

```json
[
  {
    "completed_utc": "2026-11-05T09:12:44+00:00",
    "bundles": ["baseline-0123456789ab"],
    "files": 7,
    "bytes": 48213,
    "skipped": []
  }
]
```

## Running on a schedule

To back up after every study, run the command at the end of your scenario script, or
schedule it with the operating system's task scheduler. Keep the SAS URL in the
scheduler's secure environment settings, not in the script.

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `Set MERIDIAN_BACKUP_SAS_URL ...` | The variable is not set in this shell. Export it, or set it in the scheduler's environment. |
| `The SAS URL must use https` | The URL was copied without its scheme or with `http`. Generate the SAS with HTTPS only. |
| `The SAS URL must include its token` | Only the account address was copied. Copy the full "Blob service SAS URL". |
| `Upload of ... rejected (HTTP 404)` | The container does not exist. Create it in the storage account first. |
| `Cannot list the backup container (HTTP 403)` | The SAS lacks List permission or has expired. |
| `Skipped <bundle>: failed verification` | A file in that bundle was edited after the run. Re-run the scenario. |

## Security notes

- Keep the SAS URL out of scripts, notebooks and tickets; use environment variables or a
  secret store.
- Prefer a SAS scoped to the storage account used only for Meridian backups, with the
  shortest expiry that suits your schedule.
- Results are synthetic in this repository, but real planning data would be commercially
  sensitive: enable encryption at rest (on by default in Azure) and restrict network
  access to the storage account where possible.
- `restore` verifies every downloaded bundle, so a file changed in the container is
  detected before it can be used in a comparison.

## Storage cost

Bundles are small (tens of kilobytes for the example scenarios), so storage cost is
negligible. Use the Cool access tier for long-term retention.

## Limits

- Only Azure Blob Storage is supported.
- Deleting a local bundle does not delete its backup; manage retention with the storage
  account's lifecycle rules.
