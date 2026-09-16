# Security policy

## Reporting a vulnerability

**Please do not open a public issue.**

Report privately through GitHub's
[Report a vulnerability](https://github.com/F0xhopper/Peritus/security/advisories/new) form, which
opens a draft advisory only you and the maintainer can see.

Please include what you can: the affected component (`api/`, `web/`, `cli/`), the version or commit,
what an attacker gains, and the smallest reproduction you have. A proof of concept is welcome; a
working exploit against the hosted deployment is not necessary and is not wanted.

Expect an acknowledgement within a few days. This is a personal project with no on-call rotation, so
please do not expect an immediate response.

## Scope

Peritus is pre-1.0 and only the `main` branch is supported. There are no security patches for older
commits.

In scope:

- Authentication and session handling (Supabase tokens, the refresh flow, cookie shaping)
- Cross-tenant access: anything that lets one account read, chat with or mutate another's expert
- Share links and grants
- Injection of any kind, including prompt injection that escapes the grounding contract
- Secrets leaking into responses, logs or the client bundle

Out of scope:

- Findings that require an already-compromised account or machine
- Missing hardening headers with no demonstrated impact
- Volumetric denial of service
- Output from the underlying models being wrong, biased or unhelpful — Peritus publishes no accuracy
  claims (see [docs/audit-api.md](docs/audit-api.md))

## For operators

If you run your own deployment, three settings decide whether it is safe:

1. **`PERITUS_ENV=production`.** The server then refuses to start with auth disabled. Without it, a
   missing `SUPABASE_URL` silently turns every request into the bootstrap admin. This is the single
   most important setting in the system.
2. **`SUPABASE_ANON_KEY` is server-side only.** The API is a backend-for-frontend and is the only
   thing that should ever hold it. The browser holds no token in JavaScript — the session lives in
   two httpOnly cookies.
3. **`AUTH_ALLOW_SIGNUP=false`** for an invite-only deployment, so unknown emails cannot
   self-provision. `/auth/otp` and `/auth/verify` are rate-limited per IP either way.

Note that provider API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and the rest) are spending
credentials: anyone who can enqueue builds on your deployment can spend your money, bounded only by
the per-build spend caps and the credit ledger.

Passages retrieved from a corpus are treated as **data, never instructions** — the grounding
contract says so explicitly — but a corpus is assembled from the open web. Treat a shared expert's
sources with the same suspicion you would treat any user-supplied content.
