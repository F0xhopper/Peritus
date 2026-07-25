import type { ChatStreamEvent } from "@/lib/api/types";

// EventSource can only GET and can't send a body, so chat streams are read
// straight off a fetch ReadableStream instead. No reconnection logic: a broken
// answer is completed server-side as `interrupted`, and the client just
// refetches the conversation rather than trying to resume a half-stream.

/** Non-2xx before the stream opens (409 busy, 404 gone, 401 expired). */
export class ChatStreamError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** POST `body` to `path` and yield each SSE `data:` payload as a typed event. */
export async function* streamChat(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
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
        const event = parseFrame(frame);
        if (event) yield event;
      }
    }
    const last = parseFrame(buffer);
    if (last) yield last;
  } finally {
    // Abort mid-stream leaves the body undrained; cancelling releases it and
    // closes the socket so the server sees the disconnect promptly.
    await reader.cancel().catch(() => {});
  }
}

const FRAME_SEPARATOR = /\r?\n\r?\n/;
const LINE_SEPARATOR = /\r?\n/;

function parseFrame(frame: string): ChatStreamEvent | null {
  // A frame may carry `id:`/`event:` lines too; only `data:` matters here, and
  // multi-line data payloads concatenate per the SSE spec.
  const data = frame
    .split(LINE_SEPARATOR)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim())
    .join("\n");

  if (!data) return null;
  try {
    return JSON.parse(data) as ChatStreamEvent;
  } catch {
    // A frame we can't parse is not worth killing the stream over.
    return null;
  }
}
