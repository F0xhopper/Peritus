'use client'

import { useCallback, useSyncExternalStore } from 'react'

/**
 * A per-viewer preference in `localStorage`.
 *
 * `useSyncExternalStore` rather than an effect, because that is what
 * `localStorage` is: an external store this component reads, with a **server
 * snapshot** for the render that happens before any browser exists. Reading it
 * in a lazy `useState` initialiser would produce a hydration mismatch; reading
 * it in an effect would paint the default first and then cascade a second
 * render.
 *
 * It is only ever used for conveniences that may be silently lost — a chosen
 * column set, a collapsed section. Anything that has to survive a new device,
 * be shared, or be read back by the API belongs on the server.
 */

// `getSnapshot` must return a referentially stable value or React re-renders
// forever, so parsed values are memoised per key against their raw string.
const cache = new Map<string, { raw: string | null; value: unknown }>()

const listeners = new Set<() => void>()

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange)
  // Another tab writing the same key should be reflected here.
  const onStorage = () => onChange()
  window.addEventListener('storage', onStorage)
  return () => {
    listeners.delete(onChange)
    window.removeEventListener('storage', onStorage)
  }
}

function emit() {
  for (const listener of listeners) listener()
}

export function useStoredPreference<T>(
  key: string,
  fallback: T,
  parse: (raw: string) => T | null,
): [T, (value: T, serialise: (value: T) => string) => void] {
  const getSnapshot = useCallback((): T => {
    let raw: string | null = null
    try {
      raw = localStorage.getItem(key)
    } catch {
      // A private window, or site data blocked. The fallback is correct.
      return fallback
    }
    const cached = cache.get(key)
    if (cached && cached.raw === raw) return cached.value as T
    let value = fallback
    if (raw !== null) {
      try {
        value = parse(raw) ?? fallback
      } catch {
        value = fallback
      }
    }
    cache.set(key, { raw, value })
    return value
  }, [key, fallback, parse])

  const getServerSnapshot = useCallback(() => fallback, [fallback])

  const value = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)

  const set = useCallback(
    (next: T, serialise: (value: T) => string) => {
      try {
        const raw = serialise(next)
        localStorage.setItem(key, raw)
        cache.set(key, { raw, value: next })
      } catch {
        // Not worth surfacing: the change still applies for this render pass.
        cache.set(key, { raw: null, value: next })
      }
      emit()
    },
    [key],
  )

  return [value, set]
}
