/**
 * Build an auth-page URL, dropping empty parameters.
 *
 * Every link between the sign-in pages carries `next` so the destination
 * survives a detour through "forgot password" or "create an account".
 */
export function authHref(
  path: string,
  params: Record<string, string | null | undefined> = {}
): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (!value) continue
    search.set(key, value)
  }
  const qs = search.toString()
  return qs ? `${path}?${qs}` : path
}
