import type { BuildEvent, ChatStreamEvent } from "@/lib/api/types";

// EventSource can only GET and can't send a body, so these streams are read
// straight off a fetch ReadableStream instead. That also keeps every stream on
// the same code path — chat POSTs a question, builds GET a resumable log.

/** Non-2xx before the stream opens (409 busy, 404 gone, 401 expired). */
export class ChatStreamError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Open `path` and yield each SSE `data:` payload, parsed as `T`.
 *
 * Callers own reconnection. Chat doesn't reconnect (a broken answer is
 * completed server-side as `interrupted`); builds do, because their event log
 * is durable and replayable from a cursor. */
export async function* streamSse<T>(
  path: string,
  init?: RequestInit,
): AsyncGenerator<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!res.ok || !res.body) {
    const message = await res
      .json()
      .then((j) => j.error as string)
      .catch(() => res.statusText);
    throw new ChatStreamError(res.status, message || "The stream failed to open.");
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += value;
      // SSE frames are separated by a blank line; anything after the last one
      // is a partial frame that stays buffered until its terminator arrives.
      // sse-starlette terminates with CRLF, so matching only "\n\n" silently
      // parses nothing at all — split on either form.
      const frames = buffer.split(FRAME_SEPARATOR);
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const event = parseFrame<T>(frame);
        if (event) yield event;
      }
    }
    const last = parseFrame<T>(buffer);
    if (last) yield last;
  } finally {
    // Abort mid-stream leaves the body undrained; cancelling releases it and
    // closes the socket so the server sees the disconnect promptly.
    await reader.cancel().catch(() => {});
  }
}

/** POST `body` to `path` and yield each SSE payload as a typed chat event. */
export function streamChat(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  return streamSse<ChatStreamEvent>(path, {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}

/** Tail an expert's durable build log from `after` (a `seq` cursor).
 *
 * Every event is persisted, so `after=0` replays the whole build from the
 * start and a reconnect resumes exactly where it stopped — nothing is lost by
 * dropping the connection, which is what makes retrying safe. */
export function streamBuildEvents(
  slug: string,
  after: number,
  signal?: AbortSignal,
): AsyncGenerator<BuildEvent> {
  const path = `/api/experts/${encodeURIComponent(slug)}/build/events?after=${after}`;
  return streamSse<BuildEvent>(path, { method: "GET", signal });
}

const FRAME_SEPARATOR = /\r?\n\r?\n/;
const LINE_SEPARATOR = /\r?\n/;

/** SSE `id:` lines carry the build log's `seq`, which is the resume cursor.
 * Chat ignores it; the build stream needs it, so it is parsed out here and
 * attached rather than thrown away with the rest of the frame. */
function parseFrame<T>(frame: string): T | null {
  const lines = frame.split(LINE_SEPARATOR);

  // A frame may carry `id:`/`event:` lines too; multi-line data payloads
  // concatenate per the SSE spec.
  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim())
    .join("\n");

  if (!data) return null;

  const idLine = lines.find((line) => line.startsWith("id:"));
  const seq = idLine ? Number(idLine.slice(3).trim()) : NaN;

  try {
    const parsed = JSON.parse(data) as T;
    if (Number.isFinite(seq)) {
      (parsed as T & { seq?: number }).seq = seq;
    }
    return parsed;
  } catch {
    // A frame we can't parse is not worth killing the stream over.
    return null;
  }
}
