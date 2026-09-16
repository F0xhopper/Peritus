/**
 * Writing a response, the way FastAPI writes one.
 *
 * Small enough to inline and separate anyway, because the *shapes* here are
 * what the client is built against: `Content-Length` on every JSON body, a
 * bare 204 with no body at all, and the SSE headers `sse-starlette` sends —
 * including `X-Accel-Buffering: no`, without which a proxy would buffer the
 * stream and the reconnect tests would pass for the wrong reason.
 */

export function json(res, status, body, headers = {}) {
  const payload = JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
    ...headers,
  })
  res.end(payload)
}

export function noContent(res) {
  res.writeHead(204)
  res.end()
}

export function sseHead(res) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  })
}

/** One frame, CRLF-terminated as sse-starlette emits. */
export function frame(res, seq, payload) {
  res.write(`id: ${seq}\r\ndata: ${JSON.stringify(payload)}\r\n\r\n`)
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** Read a whole request body. */
export async function body(req) {
  const chunks = []
  for await (const chunk of req) chunks.push(chunk)
  return Buffer.concat(chunks)
}

/** The server's own slugify — the client never does this. */
export function slugify(topic) {
  return topic
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
}
