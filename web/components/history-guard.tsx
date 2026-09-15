'use client'

/**
 * Keeps a dying document from taking the page down in Safari.
 *
 * Next's app router syncs its state into `history.replaceState` from an effect
 * that runs whenever the router state commits — including the commit that
 * lands when a `router.refresh()` response arrives. If a reload or a top-level
 * navigation has already been committed by then, the document is no longer
 * "fully active", and **WebKit throws `SecurityError` from the History API in
 * that state** where Chromium quietly ignores the call. That throw happens
 * inside the router's own effect, above every boundary this app can declare,
 * so React escalates it to Next's built-in "This page couldn't load" screen —
 * which is what the reader is left looking at.
 *
 * It is reachable from ordinary use: save an avatar (or finish a chat, or
 * delete an expert — anything that calls `router.refresh()`) and reload or
 * navigate away before the refresh lands. The e2e suite hits it on iOS Safari
 * every run; the desktop projects never do.
 *
 * Swallowing the error is safe *because* of what the error means: the document
 * cannot touch its own session history any more, and there is no state worth
 * preserving in a document that is already being replaced. Only `SecurityError`
 * is swallowed, so a genuine misuse of the History API still surfaces.
 *
 * Installed at module scope rather than in an effect on purpose: the router's
 * effect captures whatever `history.replaceState` is at the time it mounts, so
 * the wrapper has to be in place before any effect runs. Module evaluation
 * happens during the client bootstrap, which is strictly earlier.
 */
const GUARD = '__peritusHistoryGuard'

type Guarded = typeof globalThis & { [GUARD]?: true }

function install() {
  const guarded = globalThis as Guarded
  if (guarded[GUARD]) return
  guarded[GUARD] = true

  for (const method of ['replaceState', 'pushState'] as const) {
    const original = history[method].bind(history)
    Object.defineProperty(history, method, {
      configurable: true,
      writable: true,
      value: function guardedHistoryMethod(data: unknown, unused: string, url?: string | URL | null) {
        try {
          original(data, unused, url)
        } catch (error) {
          if (error instanceof DOMException && error.name === 'SecurityError') return
          throw error
        }
      },
    })
  }
}

if (typeof window !== 'undefined') install()

/** Renders nothing; importing it is the point. */
export function HistoryGuard() {
  return null
}
