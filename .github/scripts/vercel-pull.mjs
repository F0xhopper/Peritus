// `vercel pull`, for a project-scoped access token.
//
// The CI secret is a Vercel *project* token (`vcp_…`): it can read the project,
// its environment variables and create deployments, which is everything CI
// needs and nothing more. `vercel build` and `vercel deploy --prebuilt` accept
// it. `vercel pull` does not — it first calls `/v2/user` (404) and
// `/teams/{id}` (403) for a project token and gives up with "Could not retrieve
// Project Settings", even though the project request itself succeeds.
//
// So this writes the two files `vercel pull` would, from the REST API:
//   .vercel/project.json             the link: project, team, build settings
//   .vercel/.env.<target>.local      that target's variables, decrypted
//
// Usage (from web/): node ../.github/scripts/vercel-pull.mjs preview|production
// Env: VERCEL_TOKEN, VERCEL_ORG_ID, VERCEL_PROJECT_ID.

import { mkdir, writeFile } from 'node:fs/promises'

const target = process.argv[2]
if (!['preview', 'production', 'development'].includes(target)) {
  throw new Error(`usage: vercel-pull.mjs preview|production (got ${target})`)
}
const { VERCEL_TOKEN: token, VERCEL_ORG_ID: teamId, VERCEL_PROJECT_ID: projectId } = process.env
for (const [name, value] of Object.entries({ VERCEL_TOKEN: token, VERCEL_ORG_ID: teamId, VERCEL_PROJECT_ID: projectId })) {
  if (!value) throw new Error(`${name} is not set`)
}

async function api(path) {
  const url = `https://api.vercel.com${path}${path.includes('?') ? '&' : '?'}teamId=${teamId}`
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
  const body = await res.json()
  if (!res.ok) throw new Error(`${res.status} from ${path}: ${JSON.stringify(body.error ?? body)}`)
  return body
}

const project = await api(`/v9/projects/${projectId}`)
const settings = {
  createdAt: project.createdAt,
  framework: project.framework ?? null,
  devCommand: project.devCommand ?? null,
  installCommand: project.installCommand ?? null,
  buildCommand: project.buildCommand ?? null,
  outputDirectory: project.outputDirectory ?? null,
  rootDirectory: project.rootDirectory ?? null,
  directoryListing: project.directoryListing ?? false,
  nodeVersion: project.nodeVersion ?? null,
}

// The list endpoint returns encrypted values; the per-variable endpoint
// decrypts one at a time.
const { envs } = await api(`/v10/projects/${projectId}/env`)
const lines = []
for (const env of envs.filter((e) => e.target?.includes(target))) {
  const { value } = await api(`/v1/projects/${projectId}/env/${env.id}`)
  if (value === undefined) throw new Error(`could not read ${env.key}`)
  if (value) console.log(`::add-mask::${value}`)
  lines.push(`${env.key}=${JSON.stringify(value)}`)
}

await mkdir('.vercel', { recursive: true })
await writeFile(
  '.vercel/project.json',
  JSON.stringify({ projectId, orgId: teamId, projectName: project.name, settings }, null, 2),
)
await writeFile(`.vercel/.env.${target}.local`, `${lines.join('\n')}\n`)
console.log(`Linked ${project.name}; wrote ${lines.length} ${target} variables: ${envs.filter((e) => e.target?.includes(target)).map((e) => e.key).join(', ')}`)
