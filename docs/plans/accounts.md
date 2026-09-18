# Accounts: sign-up, sign-in and account management

Written 2026-09-18. Branch `feat/accounts`.

## Where it starts

Peritus signs people in two ways, both through the FastAPI backend-for-frontend
(`api/src/peritus/api/routes/auth.py`) so no client ever holds the Supabase anon
key or a token in JavaScript:

- **Email code (OTP).** `/login` → `/login/verify`, six digits, no password.
- **Google (PKCE).** `/api/auth/google/start` → Supabase → Google →
  `/api/auth/callback`.

There is no password, no explicit sign-up, no way to recover anything, and the
Settings page shows an email, an id and one button: "Sign out everywhere". An
account cannot be renamed, moved to another email, linked to Google after the
fact, inspected for sessions or deleted.

Supabase project facts (`GET /auth/v1/settings`, 2026-09-18): email and Google
providers on, sign-ups open, `mailer_autoconfirm: false` (so a new password
account must confirm its email before it can sign in).

## What "best practice" means here

These are the rules the implementation follows. Most come from OWASP ASVS v4
§2–3 and NIST SP 800-63B; the rest are Supabase's own guidance.

1. **Three ways in, one account.** Google, email + password, and an emailed
   code all resolve to the same Supabase user. Supabase links identities that
   share a verified email automatically.
2. **No account enumeration.** Sign-up, "forgot password" and code requests
   answer the same way whether or not the email exists. A wrong password and an
   unknown email give the same message. The only exception is "email not
   confirmed", which is only reachable with the right password.
3. **Passwords (NIST 800-63B §5.1.1).** At least 8 characters, at most 72 (the
   bcrypt limit Supabase uses), any characters, no composition rules, no
   rotation. A strength meter advises; it does not block. Paste allowed,
   show/hide toggle, correct `autocomplete` (`current-password`,
   `new-password`) so password managers work.
4. **Changing a password needs the current one**, or, for an account that has
   never had one (Google and code users), sets one. If Supabase asks for
   reauthentication (secure password change), a code is emailed and the change
   is resubmitted with it.
5. **Changing an email confirms the new address** with a code before it takes
   effect. The old address keeps working until then.
6. **Sessions are visible and revocable.** A list of the account's signed-in
   devices (browser, IP, last active), with this one marked, "sign out" per
   device, "sign out of other devices", and "sign out everywhere".
7. **Deleting an account is real and irreversible.** Type the email to confirm.
   It removes the Supabase user and everything the account owns: experts (and
   through them sources, graph, builds, pictures, share links), conversations,
   credits, uploads, share grants. Operator accounts cannot delete themselves.
8. **Every unauthenticated endpoint is rate-limited** per IP
   (`auth_rate_limit`), and every step that sends an email is too.
9. **Recovery is by code, not by a magic link.** The whole product is code-based
   already (the CLI and TUI cannot follow a link), codes work when the email is
   opened on another device, and a link in an unverified sending domain is a
   phishing shape.
10. **Tokens stay server-side.** Every new flow ends the way the existing ones
    do: the route handler receives the session and turns it into the two
    httpOnly cookies; the response body carries only the user.

## API (FastAPI, `routes/auth.py` + new `routes/account.py`)

Unauthenticated, all behind `auth_rate_limit`:

| Endpoint | GoTrue call | Notes |
|---|---|---|
| `POST /auth/password/login` `{email, password}` | `POST /token?grant_type=password` | 400 → "Incorrect email or password." whatever GoTrue said; `email_not_confirmed` → 403 with `code` so the web can route to the code page |
| `POST /auth/signup` `{email, password, name?}` | `POST /signup` | 403 when `AUTH_ALLOW_SIGNUP` is off. Returns `{confirmation_required}` or a session when the project auto-confirms. An existing email gets the same 202 (GoTrue obfuscates it) |
| `POST /auth/resend` `{email}` | `POST /resend {type: signup}` | 204 always, except 429 |
| `POST /auth/verify` `{email, token, type?}` | `POST /verify` | `type` now `email` (default) or `signup` |
| `POST /auth/password/forgot` `{email}` | `POST /recover` | 204 always, except 429 |
| `POST /auth/password/reset` `{email, token, password}` | `POST /verify {type: recovery}` then `PUT /user` | returns a session — the reset signs you in |

Authenticated (`require_user`), under `/auth/account`:

| Endpoint | How |
|---|---|
| `GET /auth/account` | `GET /user` (identities, metadata, timestamps) + `auth.users.encrypted_password` for `has_password` |
| `PATCH /auth/account` `{name}` | `PUT /user {data: {full_name}}` |
| `POST /auth/account/password` `{password, current_password?, nonce?}` | checks `current_password` with a password grant when the account has one; `PUT /user`; `reauthentication_needed` → 409 |
| `POST /auth/account/reauthenticate` | `GET /reauthenticate` (emails a code) |
| `POST /auth/account/email` `{email}` | `PUT /user {email}` — GoTrue emails the new address |
| `POST /auth/account/email/verify` `{email, token}` | `POST /verify {type: email_change}` → session |
| `GET /auth/account/identities/authorize` | `GET /user/identities/authorize?skip_http_redirect=true` — PKCE, same callback |
| `DELETE /auth/account/identities/{id}` | `DELETE /user/identities/{id}`; refuses the last identity |
| `GET /auth/account/sessions` | `auth.sessions` for this user; current = JWT `session_id` |
| `DELETE /auth/account/sessions/{id}` | delete from `auth.sessions` where it is this user's (refresh tokens cascade) |
| `POST /auth/logout?scope=local\|others\|global` | existing route, now with a scope |
| `DELETE /auth/account` `{confirm_email}` | one transaction: rows without an FK cascade, then `auth.users` |

The session and deletion endpoints read `auth.*` through the API's own Postgres
connection (the service role). They return 503 where the `auth` schema does not
exist (local Postgres), rather than pretending there are no sessions.

`AuthUser` gains `session_id` from the JWT.

## Web

**Components**, shadcn's shapes on the existing Base UI tokens (AGENTS.md: the
design fights shadcn's default theme, so the source is ported, not installed):

- `components/ui/field.tsx` — shadcn's `Field`, `FieldGroup`, `FieldLabel`,
  `FieldDescription`, `FieldError`, `FieldSeparator`, `FieldSet`, `FieldLegend`.
- `components/ui/card.tsx` — `Card`, `CardHeader`, `CardTitle`,
  `CardDescription`, `CardContent`, `CardFooter`.
- `components/auth/password-input.tsx` — show/hide, optional strength meter.

**Pages** (the shadcn `login-03` block, adapted):

| Route | Form |
|---|---|
| `/login` | Google · "or" · email + password (Forgot?) · Sign in · "Email me a code instead" · Sign up |
| `/signup` | Google · "or" · name, email, password with meter · Create account · Sign in |
| `/login/code` | the existing email-code form |
| `/login/verify` | the existing code cells; `?type=signup` confirms a new account and resends through `/auth/resend` |
| `/login/forgot` | email → code sent |
| `/login/reset` | code + new password → signed in |

**Settings → Account** becomes sections: Profile (name, avatar initial), Email
(change with code), Password (set or change), Sign-in methods (Google
link/unlink, email), Sessions (list, revoke, others, everywhere), Delete account.

**Route handlers**: one per API endpoint, `guardOrigin` on every mutation;
flows that mint a session set the cookies exactly as `/api/auth/verify` does.
Deleting the account and signing out clear the cookies on the response.

## Tests

- API: `tests/api/test_auth_accounts.py` — GoTrue mocked; enumeration
  resistance, error mapping, signup gate, reset chain, current-password check,
  identity guard, deletion confirmation.
- Web unit: password rules.
- e2e: mock API gains the new endpoints; `auth.spec.ts` covers password sign-in,
  sign-up → code, forgot → reset, the code path; `account.spec.ts` covers the
  settings sections. Every page still passes the 360px / tap-target checks.

## Owed outside the code (Supabase dashboard)

These cannot be set from this repo and each one breaks a flow if missing:

1. **Email templates must carry `{{ .Token }}`**: Confirm signup, Reset
   password, Change email address, Reauthentication (Magic link already does).
2. **Authentication → Providers → Email**: minimum password length 8; turn on
   leaked-password protection if the plan allows it.
3. **Manual identity linking** on (Authentication → Configuration) for "Link
   Google" in Settings. Without it the button reports that linking is off.
4. **Redirect URLs**: `https://peritus-app.vercel.app/api/auth/callback` and the
   localhost one (already owed, see `docs/deployment.md`).
5. **Resend is sandboxed** — until a domain is verified, only the owner's
   address receives any of these emails.
