import { body, json, noContent } from './http.mjs'

/**
 * The account endpoints: password sign-in, sign-up, recovery and everything
 * under `/auth/account`.
 *
 * Deterministic on purpose. One password (`correct-password`) and one code
 * (`123456`) work; an email containing `unconfirmed`, `closed` or
 * `ratelimited` triggers that branch. Enough to drive every path a form has,
 * with nothing that depends on timing.
 */

export const PASSWORD = 'correct-password'
export const CODE = '123456'
const USER_ID = '11111111-1111-1111-1111-111111111111'
const CURRENT_SESSION = 'aaaaaaaa-0000-0000-0000-000000000001'

function fresh() {
  return {
    email: 'tester@example.com',
    new_email: null,
    name: 'Test Person',
    has_password: true,
    identities: [
      {
        id: 'bbbbbbbb-0000-0000-0000-000000000001',
        provider: 'email',
        email: 'tester@example.com',
        created_at: '2026-09-01T09:00:00.000Z',
        last_sign_in_at: '2026-09-18T09:00:00.000Z',
      },
    ],
    sessions: [
      {
        id: CURRENT_SESSION,
        current: true,
        created_at: '2026-09-18T09:00:00.000Z',
        last_active_at: '2026-09-18T09:30:00.000Z',
        user_agent:
          'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
      },
      {
        id: 'aaaaaaaa-0000-0000-0000-000000000002',
        current: false,
        created_at: '2026-09-10T09:00:00.000Z',
        last_active_at: '2026-09-17T20:00:00.000Z',
        user_agent:
          'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/140.0 Mobile/15E148 Safari/604.1',
      },
    ],
    deleted: false,
  }
}

let account = fresh()

export function resetAccount() {
  account = fresh()
}

function session(email) {
  return {
    access_token: 'mock-access',
    refresh_token: 'mock-refresh',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: null,
    user: { id: USER_ID, email },
  }
}

const coded = (res, status, code, message) => json(res, status, { detail: { code, message } })
const rateLimited = (res) =>
  json(res, 429, { detail: 'Too many requests' }, { 'Retry-After': '30' })

function accountOut() {
  return {
    id: USER_ID,
    email: account.email,
    new_email: account.new_email,
    name: account.name,
    avatar_url: null,
    is_admin: false,
    has_password: account.has_password,
    email_confirmed: true,
    identities: account.identities,
    created_at: '2026-09-01T09:00:00.000Z',
    last_sign_in_at: '2026-09-18T09:00:00.000Z',
  }
}

async function read(req) {
  const raw = (await body(req)).toString()
  return raw ? JSON.parse(raw) : {}
}

/** Returns true when it answered. */
export async function handleAccount(req, res, path, method, url) {
  // ── anonymous ──
  if (path === '/auth/password/login' && method === 'POST') {
    const { email, password } = await read(req)
    if (String(email).includes('ratelimited')) return (rateLimited(res), true)
    if (String(email).includes('unconfirmed')) {
      return (
        coded(
          res,
          403,
          'email_not_confirmed',
          'Confirm your email first — we have sent you a code.'
        ),
        true
      )
    }
    if (password !== PASSWORD) {
      return (coded(res, 400, 'invalid_credentials', 'Incorrect email or password.'), true)
    }
    return (json(res, 200, session(email)), true)
  }
  if (path === '/auth/signup' && method === 'POST') {
    const { email } = await read(req)
    if (String(email).includes('closed')) {
      return (coded(res, 403, 'signup_disabled', 'Sign-ups are closed on this server.'), true)
    }
    if (String(email).includes('ratelimited')) return (rateLimited(res), true)
    return (json(res, 202, { confirmation_required: true, session: null }), true)
  }
  if ((path === '/auth/resend' || path === '/auth/password/forgot') && method === 'POST') {
    const { email } = await read(req)
    if (String(email).includes('ratelimited')) return (rateLimited(res), true)
    return (noContent(res), true)
  }
  if (path === '/auth/password/reset' && method === 'POST') {
    const { email, token } = await read(req)
    if (token !== CODE) {
      return (
        coded(res, 400, 'invalid_code', 'That code is wrong or has expired. Ask for a new one.'),
        true
      )
    }
    return (json(res, 200, session(email)), true)
  }

  if (!path.startsWith('/auth/account')) return false

  // ── signed in ──
  if (path === '/auth/account' && method === 'GET') return (json(res, 200, accountOut()), true)
  if (path === '/auth/account' && method === 'PATCH') {
    const { name } = await read(req)
    account.name = name || null
    return (json(res, 200, accountOut()), true)
  }
  if (path === '/auth/account' && method === 'DELETE') {
    const { confirm_email: typed } = await read(req)
    if (String(typed).trim().toLowerCase() !== account.email) {
      return (
        coded(res, 400, 'confirmation_mismatch', 'Type your email address exactly to confirm.'),
        true
      )
    }
    account.deleted = true
    return (json(res, 200, { experts_deleted: 3, conversations_deleted: 2 }), true)
  }
  if (path === '/auth/account/password' && method === 'POST') {
    const { password, current_password: current } = await read(req)
    if (account.has_password && current !== PASSWORD) {
      return (
        coded(res, 400, 'invalid_current_password', 'Your current password is incorrect.'),
        true
      )
    }
    if (password === PASSWORD) {
      return (
        coded(res, 422, 'same_password', 'That is already your password. Choose a new one.'),
        true
      )
    }
    account.has_password = true
    return (noContent(res), true)
  }
  if (path === '/auth/account/reauthenticate' && method === 'POST') return (noContent(res), true)
  if (path === '/auth/account/email' && method === 'POST') {
    const { email } = await read(req)
    account.new_email = String(email).toLowerCase()
    return (json(res, 202, { email: account.new_email }), true)
  }
  if (path === '/auth/account/email/verify' && method === 'POST') {
    const { token } = await read(req)
    if (token !== CODE) {
      return (coded(res, 400, 'invalid_code', 'That code is wrong or has expired.'), true)
    }
    account.email = account.new_email ?? account.email
    account.new_email = null
    return (
      json(res, 200, { complete: true, session: session(account.email), message: null }),
      true
    )
  }
  if (path === '/auth/account/identities/authorize') {
    // Straight back to the callback with a code, as the sign-in mock does.
    const redirect = url.searchParams.get('redirect_to')
    account.identities.push({
      id: 'bbbbbbbb-0000-0000-0000-000000000002',
      provider: 'google',
      email: account.email,
      created_at: '2026-09-18T10:00:00.000Z',
      last_sign_in_at: null,
    })
    return (json(res, 200, { url: `${redirect}?code=mock-auth-code` }), true)
  }
  const identity = path.match(/^\/auth\/account\/identities\/([^/]+)$/)
  if (identity && method === 'DELETE') {
    if (account.identities.length < 2) {
      return (
        coded(
          res,
          409,
          'single_identity_not_deletable',
          'This is your only way to sign in, so it cannot be removed.'
        ),
        true
      )
    }
    account.identities = account.identities.filter((row) => row.id !== identity[1])
    return (noContent(res), true)
  }
  if (path === '/auth/account/sessions' && method === 'GET') {
    return (json(res, 200, account.sessions), true)
  }
  const sessionMatch = path.match(/^\/auth\/account\/sessions\/([^/]+)$/)
  if (sessionMatch && method === 'DELETE') {
    if (sessionMatch[1] === CURRENT_SESSION) {
      return (json(res, 400, { detail: 'That is this device — use Sign out instead.' }), true)
    }
    const before = account.sessions.length
    account.sessions = account.sessions.filter((row) => row.id !== sessionMatch[1])
    if (account.sessions.length === before)
      return (json(res, 404, { detail: 'No such session.' }), true)
    return (noContent(res), true)
  }
  return false
}

/** `POST /auth/logout?scope=others` ends every other session. */
export function logoutOthers() {
  account.sessions = account.sessions.filter((row) => row.current)
}
