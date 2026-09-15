'use client'

/**
 * The last resort: an error in the root layout itself.
 *
 * `global-error` replaces the whole document, so it must supply its own `<html>`
 * and `<body>` — and it does **not** get the app's global styles, which means
 * no tokens, no fonts, and no theme. Everything here is therefore inline and
 * keyed on `prefers-color-scheme` directly; reaching for a token would
 * silently render black on black.
 *
 * `metadata` is not available in a Client Component, so the title is React's
 * `<title>`.
 */
export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string }
  retry: () => void
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100dvh',
          display: 'grid',
          placeItems: 'center',
          padding: '1.5rem',
          fontFamily: 'ui-sans-serif, system-ui, sans-serif',
          background: '#0e0e10',
          color: '#a1a1a8',
        }}
      >
        <title>Peritus — something went wrong</title>
        <main style={{ maxWidth: '28rem', textAlign: 'center' }}>
          <h1 style={{ margin: 0, fontSize: '1.125rem', fontWeight: 500, color: '#ececee' }}>
            Peritus could not start
          </h1>
          <p style={{ marginTop: '0.5rem', fontSize: '0.875rem', lineHeight: 1.6 }}>
            {error.message || 'An unexpected error broke the page shell.'}
          </p>
          {error.digest && (
            <p
              style={{
                marginTop: '0.5rem',
                fontFamily: 'ui-monospace, monospace',
                fontSize: '0.75rem',
                color: '#6b6b73',
              }}
            >
              digest {error.digest}
            </p>
          )}
          <button
            type="button"
            onClick={() => retry()}
            style={{
              marginTop: '1rem',
              height: '2.5rem',
              padding: '0 1rem',
              border: 0,
              borderRadius: '8px',
              background: '#8b7cf6',
              color: '#12121a',
              fontSize: '0.875rem',
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  )
}
