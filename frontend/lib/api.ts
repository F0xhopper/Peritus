/**
 * Peritus API client helpers.
 * All requests proxy through Next.js rewrites to http://localhost:8000.
 */

const BASE = "";

export interface ExpertSummary {
  slug: string;
  topic: string;
  persona_name: string;
  status: string;
  source_count: number;
  node_count: number;
  relation_count: number;
  description: string;
  created_at: string;
}

export type Difficulty = "beginner" | "intermediate" | "advanced" | "custom";

// ---------------------------------------------------------------------------
// Experts
// ---------------------------------------------------------------------------

export async function fetchExperts(): Promise<ExpertSummary[]> {
  const res = await fetch(`${BASE}/api/experts`);
  if (!res.ok) throw new Error(`Failed to fetch experts: ${res.status}`);
  return res.json();
}

export async function fetchExpert(slug: string): Promise<ExpertSummary> {
  const res = await fetch(`${BASE}/api/experts/${slug}`);
  if (!res.ok) throw new Error(`Expert not found: ${slug}`);
  return res.json();
}

/**
 * Stream expert creation progress.
 * Calls onProgress with each progress line.
 * Returns the slug when done.
 */
export async function createExpert(
  topic: string,
  onProgress: (line: string) => void
): Promise<string> {
  const res = await fetch(`${BASE}/api/experts/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let slug = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value);
    for (const line of text.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      const msg = line.replace(/^data: /, "");
      if (msg.startsWith("DONE slug=")) {
        slug = msg.replace("DONE slug=", "").trim();
      } else if (msg.startsWith("ERROR ")) {
        throw new Error(msg.replace("ERROR ", ""));
      } else {
        onProgress(msg);
      }
    }
  }
  return slug;
}

// ---------------------------------------------------------------------------
// Courses
// ---------------------------------------------------------------------------

/**
 * Stream a generated course as raw Markdown text.
 * Calls onChunk with each streamed chunk.
 */
export async function generateCourse(
  expertSlug: string,
  difficulty: Difficulty,
  focus: string | undefined,
  onChunk: (chunk: string) => void
): Promise<void> {
  const res = await fetch(`${BASE}/api/courses/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expert_slug: expertSlug, difficulty, focus }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    onChunk(decoder.decode(value));
  }
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export interface ChatHistoryItem {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export async function fetchChatHistory(slug: string): Promise<ChatHistoryItem[]> {
  const res = await fetch(`${BASE}/api/chat/${slug}/history`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.messages ?? [];
}

export async function clearChatHistory(slug: string): Promise<void> {
  await fetch(`${BASE}/api/chat/${slug}/history`, { method: "DELETE" });
}

/**
 * Send a chat message and stream the SSE response.
 * Calls onChunk with each token chunk.
 */
export async function sendChatMessage(
  slug: string,
  message: string,
  useGraph: boolean,
  onChunk: (chunk: string) => void
): Promise<void> {
  const res = await fetch(`${BASE}/api/chat/${slug}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, use_graph: useGraph }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value);
    for (const line of text.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      const data = line.replace(/^data: /, "");
      if (data === "[DONE]") return;
      if (data.startsWith("[ERROR]")) throw new Error(data.replace("[ERROR] ", ""));
      onChunk(data);
    }
  }
}
