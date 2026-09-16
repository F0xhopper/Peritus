import { describe, expect, it } from 'vitest'

import { parseFrame, readSse, seqFromId, splitFrames, streamSse } from '@/lib/api/sse'

/**
 * The SSE parser.
 *
 * These are the tests that matter most in the whole suite: this parser sits
 * under both the build log and the chat stream, and every failure mode it has
 * is silent. A dropped frame is a missing log line; a mis-read `id:` is a
 * reconnect that replays or skips events; a frame split across chunks that is
 * not buffered is a token that never arrives.
 */

/** Feed a string as a stream, optionally in the exact chunks given. */
function stream(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

async function collect<T>(iterator: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = []
  for await (const item of iterator) out.push(item)
  return out
}

describe('splitFrames', () => {
  it('splits on LF LF', () => {
    const { frames, rest } = splitFrames('data: a\n\ndata: b\n\n')
    expect(frames).toEqual(['data: a', 'data: b'])
    expect(rest).toBe('')
  })

  it('splits on CRLF CRLF, which is what sse-starlette emits', () => {
    const { frames, rest } = splitFrames('data: a\r\n\r\ndata: b\r\n\r\n')
    expect(frames).toEqual(['data: a', 'data: b'])
    expect(rest).toBe('')
  })

  it('splits on a mixture, because a proxy may rewrite one and not the other', () => {
    const { frames } = splitFrames('data: a\r\n\r\ndata: b\n\ndata: c\r\n\r\n')
    expect(frames).toEqual(['data: a', 'data: b', 'data: c'])
  })

  it('keeps an incomplete trailing frame in the buffer', () => {
    const { frames, rest } = splitFrames('data: a\n\ndata: par')
    expect(frames).toEqual(['data: a'])
    expect(rest).toBe('data: par')
  })

  it('treats a buffer with no separator as entirely incomplete', () => {
    const { frames, rest } = splitFrames('data: still arriving')
    expect(frames).toEqual([])
    expect(rest).toBe('data: still arriving')
  })
})

describe('parseFrame', () => {
  it('reads id and data', () => {
    expect(parseFrame('id: 42\ndata: {"type":"stage"}')).toEqual({
      id: '42',
      data: '{"type":"stage"}',
      event: null,
    })
  })

  it('strips exactly one space after the colon, not more', () => {
    // Two spaces means the value genuinely starts with a space.
    expect(parseFrame('data:  leading')?.data).toBe(' leading')
    expect(parseFrame('data:none')?.data).toBe('none')
  })

  it('joins multiple data lines with newlines, as the spec requires', () => {
    expect(parseFrame('data: line one\ndata: line two')?.data).toBe('line one\nline two')
  })

  it('ignores a keep-alive comment', () => {
    expect(parseFrame(': ping')).toBeNull()
  })

  it('ignores retry, because backoff is the client’s own', () => {
    expect(parseFrame('retry: 5000\ndata: x')).toEqual({ id: null, data: 'x', event: null })
  })

  it('returns null for a frame with neither data nor id', () => {
    expect(parseFrame('event: message')).toBeNull()
  })

  it('keeps an id-only frame, so a cursor is never lost', () => {
    expect(parseFrame('id: 7')).toEqual({ id: '7', data: '', event: null })
  })
})

describe('readSse', () => {
  it('yields each complete frame', async () => {
    const frames = await collect(readSse(stream('id: 1\ndata: a\n\nid: 2\ndata: b\n\n')))
    expect(frames.map((frame) => frame.data)).toEqual(['a', 'b'])
    expect(frames.map((frame) => frame.id)).toEqual(['1', '2'])
  })

  it('buffers a frame split across chunks', async () => {
    // The ordinary case for a token event, not an edge case.
    const frames = await collect(
      readSse(stream('id: 1\nda', 'ta: hel', 'lo world\r\n', '\r\nid: 2\ndata: next\r\n\r\n'))
    )
    expect(frames.map((frame) => frame.data)).toEqual(['hello world', 'next'])
  })

  it('buffers a separator split across chunks', async () => {
    const frames = await collect(readSse(stream('data: a\r', '\n\r', '\ndata: b\r\n\r\n')))
    expect(frames.map((frame) => frame.data)).toEqual(['a', 'b'])
  })

  it('yields a final frame that has no trailing blank line', async () => {
    // Losing this would lose the terminal `done` event of a short build.
    const frames = await collect(readSse(stream('data: a\n\nid: 9\ndata: done')))
    expect(frames.map((frame) => frame.data)).toEqual(['a', 'done'])
    expect(frames[1].id).toBe('9')
  })

  it('handles a multi-byte character split across chunks', async () => {
    // `TextDecoderStream` owns this, but the buffering must not defeat it.
    const encoder = new TextEncoder()
    const bytes = encoder.encode('data: café\n\n')
    const split = bytes.findIndex((_, index) => index === bytes.length - 4)
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, split))
        controller.enqueue(bytes.slice(split))
        controller.close()
      },
    })
    const frames = await collect(readSse(body))
    expect(frames[0].data).toBe('café')
  })
})

describe('streamSse', () => {
  function response(...chunks: string[]): Response {
    return new Response(stream(...chunks))
  }

  it('decodes JSON payloads with their cursor', async () => {
    const events = await collect(
      streamSse<{ type: string }>(response('id: 3\ndata: {"type":"stage"}\r\n\r\n'))
    )
    expect(events).toEqual([{ id: '3', data: { type: 'stage' } }])
  })

  it('skips a malformed frame instead of ending the stream', async () => {
    // One bad event must never end a build log the user is watching.
    const malformed: string[] = []
    const events = await collect(
      streamSse<{ type: string }>(
        response('data: not json\r\n\r\ndata: {"type":"done"}\r\n\r\n'),
        (raw) => malformed.push(raw)
      )
    )
    expect(events.map((event) => event.data)).toEqual([{ type: 'done' }])
    expect(malformed).toEqual(['not json'])
  })

  it('yields nothing for a body-less response', async () => {
    expect(await collect(streamSse(new Response(null, { status: 204 })))).toEqual([])
  })
})

describe('seqFromId', () => {
  it('reads a sequence number', () => {
    expect(seqFromId('42', 0)).toBe(42)
    expect(seqFromId('0', 7)).toBe(0)
  })

  it('falls back when there is no id, so the cursor never regresses', () => {
    expect(seqFromId(null, 12)).toBe(12)
  })

  it('falls back on anything that is not a whole non-negative number', () => {
    expect(seqFromId('abc', 5)).toBe(5)
    expect(seqFromId('-1', 5)).toBe(5)
    expect(seqFromId('1.5', 5)).toBe(5)
    expect(seqFromId('', 5)).toBe(5)
  })
})
