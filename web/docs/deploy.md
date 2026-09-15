# Deploying the web app

The web app is a backend-for-frontend: the browser never holds a token and never
calls FastAPI directly. Everything below follows from that.

## Environment

Two variables, per environment, and nothing else:

| Variable | Example | Why |
|---|---|---|
| `PERITUS_API_URL` | `https://api.peritus.example` | The FastAPI base URL. **Server-only** — naming it `NEXT_PUBLIC_*` would put the API in the browser and defeat the design. |
| `NEXT_PUBLIC_APP_URL` | `https://peritus.example` | This app's own public origin. Used to build the Google redirect and every server-side absolute URL. |

`NEXT_PUBLIC_APP_URL` is deliberately **not** derived from the request. A value
taken from `Host` works in development and then silently becomes wrong behind a
proxy that rewrites it — and the one place it is wrong is the OAuth redirect,
which fails in a way that looks like Supabase misconfiguration.

`PERITUS_ALLOW_INSECURE_COOKIES` exists only so the e2e and Lighthouse runs can
use http on loopback (WebKit refuses `Secure` cookies there, even on localhost).
**Never set it in a deployed environment.**

## Supabase

1. Authentication → Providers → **Google**: enabled, with the OAuth client ID
   and secret from Google Cloud. Google's own "Authorised redirect URI" is
   Supabase's callback (`https://<project>.supabase.co/auth/v1/callback`), not
   this app's.
2. Authentication → URL Configuration → **Redirect URLs** must contain
   `<NEXT_PUBLIC_APP_URL>/api/auth/callback` for every environment that signs
   people in, previews included. An unlisted value is not rejected by
   `/authorize` — GoTrue substitutes the project's Site URL when the code comes
   back, so the symptom is "sign-in works and lands on the wrong host", not an
   error message.
3. The magic-link email template keeps `{{ .Token }}`: this app signs in with a
   six-digit code, not a link.

## The API

Leave `CORS_ALLOW_ORIGINS` closed. The browser never calls the API, so an origin
list here would only widen the attack surface. If a future feature does call it
directly, that is the moment to open it — not now.

## Vercel (or any Node host)

- Build: `next build`. Cache `web/.next/cache` between builds —
  `turbopackFileSystemCacheForBuild` is on by default in Next 16.3 and it is the
  difference between a warm and a cold build.
- The streaming route handlers (`/api/experts/[slug]/build/events`,
  `/api/conversations/[id]/messages`, `/api/experts/build`, the source upload)
  set `dynamic = 'force-dynamic'` and their own `maxDuration`. A build runs for
  minutes but the client reconnects with `after=<seq>`, so a per-connection cap
  of 60s is fine; what must not happen is a platform default that is *shorter*
  than the handler expects.
- Security headers come from `next.config.ts` (`headers()`), not from the host,
  so they are the same everywhere and reviewable in the repo.
- `proxy.ts` (Next 16's renamed middleware) refreshes the session at the edge.
  It must run on every `(app)` route — check the host does not exclude it from
  matching, or a signed-in user's expired access token will never be refreshed.

## After the first deploy

- Field measurements: `WebVitals` posts LCP, INP and CLS to `POST /api/vitals`
  with `sendBeacon`. A lab run on a CI box says nothing about a mid-range phone
  on a real network, and the budgets in `web-design.md` §9 are written about the
  phone.
- Walk `docs/real-device-checklist.md` on hardware. It is the part of phase 9 no
  emulated suite can sign off.
