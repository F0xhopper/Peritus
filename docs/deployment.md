# Deployment

Production is two platforms, released by one GitHub Actions pipeline.

| Part | Where | URL |
|---|---|---|
| Web app (Next.js BFF) | Vercel project `eden-phillips-projects/peritus`, functions in `lhr1` | https://peritus-app.vercel.app |
| API + build worker (FastAPI, one Docker image) | Fly.io app `peritus`, region `lhr` | https://peritus.fly.dev |
| Postgres + pgvector, Auth | Supabase `kfrhxsybeukfktocgauz`, aws eu-west-2 | — |

Everything runs in London because the database does: from the API machine a
round trip to Postgres is ~6ms; from `iad`, where the app used to run, every one
crossed the Atlantic. Keep new regions next to the database.

Web-specific environment and Supabase notes are in `web/docs/deploy.md`.

## The pipeline

```
pull request ──► ci.yml ─────────────── api · api-image · web · web-e2e · web-lighthouse · cli
             └─► preview.yml ────────── Vercel preview (web/ changes), URL commented on the PR

push to main ──► deploy.yml
                  ├─ ci (calls ci.yml — the whole suite)
                  ├─ changes (paths filter)
                  ├─ deploy-api   if api/ changed    fly deploy → release_command migrations → /health, /ready
                  └─ deploy-web   if web/ changed    vercel pull → build → deploy --prebuilt --prod → smoke test
```

- **Nothing deploys unless CI passed**, and the web app deploys only after the
  API it talks to (or when the API had nothing to deploy).
- **The API deploys only when `api/` changed.** A Fly deploy restarts the worker,
  which hands running builds back to the queue. They resume, but a web-only change
  should not cost that.
- **`api-image`** builds the production Dockerfile in CI and runs it the way Fly
  does: migrations twice (the second must be a no-op), the API's `/health` and
  `/ready`, and the worker's SIGTERM drain (must exit 0).
- **The web app is built in Actions and uploaded prebuilt.** Vercel's Git
  integration is off (`web/vercel.json` → `git.deploymentEnabled: false`), so
  a push never produces a production deployment that skipped CI.
- Redeploy without a commit: Actions → **Deploy** → Run workflow → `both`/`api`/`web`.

## Configuration and secrets

**API (Fly).** Non-secret settings are in `api/fly.toml` `[env]` and reviewed in
git (`PERITUS_ENV=production`, `LOG_LEVEL`, `DATABASE_SSL`). Credentials are Fly
secrets: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SUPABASE_JWT_SECRET`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `COHERE_API_KEY`,
`EXA_API_KEY`, `MISTRAL_API_KEY`, `BOOTSTRAP_ADMIN_EMAIL`. A secret overrides
`[env]` of the same name, so do not set a secret for anything in `[env]`.

```sh
# change a secret (restarts machines)
fly secrets set -a peritus COHERE_API_KEY=...
# or stage it to go out with the next deploy
fly secrets set --stage -a peritus COHERE_API_KEY=...
```

**Web (Vercel).** `PERITUS_API_URL` and `NEXT_PUBLIC_APP_URL`, set for
Production and Preview in the project settings. `NEXT_PUBLIC_APP_URL` is
inlined at build time, so a change needs a redeploy.

**GitHub.**

| Name | Kind | Scope | What |
|---|---|---|---|
| `FLY_API_TOKEN` | secret | environment `production-api` (main only) | Fly deploy token for app `peritus` only (`fly tokens create deploy -a peritus`), 1-year expiry |
| `VERCEL_TOKEN` | secret | repository (preview + production) | Vercel access token, scope `eden-phillips-projects` |
| `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | variables | repository | from `web/.vercel/project.json` |

The `production-api` and `production-web` environments accept deployments from
`main` only.

## Dependencies are locked

`api/uv.lock` pins every Python package. The image installs it with
`uv sync --frozen` and CI tests the same set, so a deploy can never pick up a new
major release of an SDK that nobody ran. After changing `pyproject.toml`, run
`uv lock` in `api/` and commit the lock — CI's `uv lock --check` fails otherwise.

## Rollback

- **API:** `fly releases -a peritus`, then
  `fly deploy -a peritus --image registry.fly.io/peritus:<label>` with an earlier
  image label (CI labels images `git-<sha>`). Migrations are forward-only, so a
  rollback across a schema change needs that migration to be backwards-compatible.
- **Web:** `vercel rollback` from `web/` (or Promote an earlier deployment in the
  dashboard) — instant, no rebuild.

## Machines

| Process | Size | Why |
|---|---|---|
| `app` | shared-cpu-1x, 512MB, always on | the web app calls it on every navigation |
| `worker` | shared-cpu-1x, 2GB, + a standby | see the comment in `fly.toml`: 256MB made builds stall without an OOM |

`kill_timeout` is 30s: on SIGTERM the worker cancels in-flight builds and
releases them to the queue, where they resume from their readiness point.

## Known gaps

- **Local development uses the production database** (`api/.env`). A local
  worker races the Fly worker for jobs, and a local migration applies to
  production. A Supabase branch or a second project for development would end
  both.
- **Supabase auth emails are sandboxed by Resend** until a sending domain is
  verified, so email-code sign-in only delivers to the owner's address.
- One `app` machine: a host failure is downtime until Fly restarts it. Add a
  second with `fly scale count app=2 -a peritus` when that matters.
