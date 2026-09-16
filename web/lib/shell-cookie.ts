/**
 * The sidebar's collapse preference.
 *
 * In its own module, with no `'use client'`, because both sides need it: the
 * `(app)` layout reads the cookie on the server so the first HTML already has
 * the right number of columns, and the shell context writes it in the browser.
 * Exported from the client module instead, it reached the server as a client
 * *reference* rather than a string — `cookies().get(<module ref>)` is quietly
 * undefined, and the preference silently never applied.
 */
export const SIDEBAR_COOKIE = 'peritus_sidebar'

/** A year of it, and `Lax`: a layout preference, never a credential. */
export const SIDEBAR_COOKIE_ATTRS = 'path=/;max-age=31536000;SameSite=Lax'
