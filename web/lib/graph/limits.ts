/**
 * How many nodes the Graph view may be asked for.
 *
 * A plain module, not part of the client hook that fetches the graph: the old
 * `/graph` route's redirect reads `?limit=` on the server, and a function
 * exported from a `'use client'` file cannot be called there.
 *
 * The API's own bounds are 1–1500 (`GRAPH_NODES_MAX`); these are the slider's
 * stops, and anything else in a URL falls back to the default rather than 422.
 */
export const GRAPH_LIMITS = [100, 200, 400, 800, 1500] as const
export const GRAPH_LIMIT_DEFAULT = 400

export function parseGraphLimit(raw: string | null | undefined): number {
  const value = Number(raw)
  return (GRAPH_LIMITS as readonly number[]).includes(value) ? value : GRAPH_LIMIT_DEFAULT
}
