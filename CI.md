# Backend CI/CD

GitHub Actions in this repo:

1. **`test-identity`** / **`test-portfolio`** — `pytest` (integration tests stay skipped by default).
2. **`test`** — aggregator. Fails if either pytest job fails. **This is the required merge check.**
3. **`deploy`** — only on push to `main`/`master` after `test` passes. `rsync` to Lightsail (does not overwrite `.env.prod`), then `./scripts/compose-prod.sh up -d --build`.

Market has no unit tests yet, so it is not in the merge gate.

## Secrets

Repo → **Settings → Secrets and variables → Actions**:

| Secret | Value |
|--------|--------|
| `LIGHTSAIL_HOST` | `54.85.138.59` |
| `LIGHTSAIL_SSH_KEY` | Full contents of `LightsailDefaultKey-us-east-1.pem` (including `BEGIN` / `END` lines) |

`.env.prod` stays on the server. Never add it as a GitHub secret unless you later change deploy to write that file.

## Branch protection (merge gate)

After the first Actions run appears:

1. GitHub → this repo → **Settings → Rules → Rulesets → New ruleset → Branch ruleset**
2. Target pattern: `main` (and `master` if you use it)
3. **Require a pull request before merging**
4. **Require status checks to pass** → add **`test`** (the aggregator, not `test-identity` alone)
5. Save

## First Lightsail pull

The server copy was originally `scp`. After this repo exists, keep using `~/stock-backend` on the instance. Deploy rsyncs over that folder and **excludes** `.env.prod`, so production secrets remain.
