/**
 * Server-sent-event parsing, client side.
 *
 * `EventSource` is not used anywhere: the chat stream is a POST, and the build
 * stream needs the `after=` cursor on a URL the browser must not cache. Both go
 * through `fetch` and this parser.
 *
 * `sse-starlette` terminates frames with CRLF CRLF, but the spec allows LF, and
 * a proxy in between may rewrite either. The splitter accepts both and, more
 * importantly, holds a partial frame across chunk boundaries — a token event
 * arriving in two TCP segments is the normal case, not an edge case.
 */

export interface SseFrame {
  /** The `id:` line. The build stream puts the event's `seq` here. */
  id: string | null
  /** The `data:` lines, joined with newlines as the spec requires. */
  data: string
  event: string | null
}

const FRAME_SEPARATOR = /\r?\n\r?\n/

/**
 * Split a buffer into complete frames plus the remainder.
 * Exported for the unit tests, which drive it chunk by chunk.
 */
export function splitFrames(buffer: string): { frames: string[]; rest: string } {
  const parts = buffer.split(FRAME_SEPARATOR)
  // The last part is either empty (the buffer ended on a separator) or an
  // incomplete frame. Either way it stays in the buffer.
  const rest = parts.pop() ?? ''
  return { frames: parts.filter((f) => f.length > 0), rest }
}

export function parseFrame(raw: string): SseFrame | null {
  let id: string | null = null
  let event: string | null = null
  const dataLines: string[] = []

  for (const line of raw.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue // comment / keep-alive ping
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    // One optional space after the colon is part of the framing, not the value.
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'data') dataLines.push(value)
    else if (field === 'id') id = value
    else if (field === 'event') event = value
    // `retry:` is ignored — reconnect backoff is ours, in `useBuildEvents`.
  }

  if (dataLines.length === 0 && id === null) return null
  return { id, data: dataLines.join('\n'), event }
}

/**
 * Read a fetch body as a stream of frames. Yields raw frames; decoding the
 * `data` payload as JSON is the caller's job, so a single malformed event can
 * be skipped without tearing the stream down.
 */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseFrame> {
  // `TextDecoderStream`'s lib.dom type is `BufferSource`-in, which does not
  // unify with `ReadableStream<Uint8Array>` even though it accepts one. The
  // cast is the narrowing, not a loosening.
  const decoded = body.pipeThrough(
    new TextDecoderStream() as unknown as ReadableWritablePair<string, Uint8Array>,
  )
  const reader = decoded.getReader()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += value
      const { frames, rest } = splitFrames(buffer)
      buffer = rest
      for (const raw of frames) {
        const frame = parseFrame(raw)
        if (frame) yield frame
      }
    }
    // A stream that ends without a trailing blank line still has one frame in
    // it. Dropping it would lose the terminal `done` event of a short build.
    const tail = parseFrame(buffer)
    if (tail) yield tail
  } finally {
    reader.releaseLock()
  }
}

/**
 * Frames decoded as JSON, with the `id:` cursor carried alongside so a build
 * client can resume from `after=<seq>`. A frame whose data will not parse is
 * skipped and reported, never thrown: one bad event must not end a build log.
 */
export async function* streamSse<T>(
  res: Response,
  onMalformed?: (raw: string) => void,
): AsyncGenerator<{ id: string | null; data: T }> {
  if (!res.body) return
  for await (const frame of readSse(res.body)) {
    if (!frame.data) continue
    let data: T
    try {
      data = JSON.parse(frame.data) as T
    } catch {
      onMalformed?.(frame.data)
      continue
    }
    yield { id: frame.id, data }
  }
}

/**
 * `id:` as a sequence number, or the previous cursor when it is not one.
 *
 * The empty-string guard is load-bearing: `Number('')` is 0, so an `id:` line
 * with no value would silently reset the cursor to zero and make the next
 * reconnect replay the entire log from the beginning.
 */
export function seqFromId(id: string | null, fallback: number): number {
  if (id === null || id.trim() === '') return fallback
  const n = Number(id)
  return Number.isInteger(n) && n >= 0 ? n : fallback
}
