/**
 * PKCE (RFC 7636) for the Google sign-in flow.
 *
 * The verifier is generated here, in a route handler, and stored in an httpOnly
 * cookie; only its S256 challenge ever leaves the server. The API's
 * `/auth/oauth/authorize` takes the challenge and hands back a GoTrue URL, and
 * `/auth/oauth/exchange` takes the verifier back at the end. Nothing about the
 * flow is reachable from page JavaScript.
 *
 * Uses Web Crypto so this file works unchanged in a route handler regardless of
 * runtime.
 */

// RFC 7636 §4.1 — 43 to 128 characters from the unreserved set. 96 random bytes
// of base64url is 128 characters, the top of the range; the API validates the
// length on exchange, so staying inside it here is not optional.
const VERIFIER_BYTES = 64 // → 86 base64url characters

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function createVerifier(): string {
  const bytes = new Uint8Array(VERIFIER_BYTES)
  crypto.getRandomValues(bytes)
  return base64UrlEncode(bytes)
}

export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64UrlEncode(new Uint8Array(digest))
}

/**
 * Only in-app paths are honoured as a post-login destination. Anything else —
 * an absolute URL, a protocol-relative `//evil.example`, a backslash Chrome
 * would normalise to a slash — collapses to the app home, so `?next=` can never
 * become an open redirect.
 */
export function safeNext(raw: string | null | undefined, fallback = '/experts'): string {
  if (!raw) return fallback
  if (!raw.startsWith('/')) return fallback
  if (raw.startsWith('//') || raw.startsWith('/\\')) return fallback
  if (raw.includes('\\')) return fallback
  return raw
}
