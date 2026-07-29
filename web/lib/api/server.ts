// Server-only helper for calling the real FastAPI backend (api/) from Next.js
// route handlers. Never imported from client components — the browser only
// ever talks to our own /api/* route handlers, never the FastAPI host
// directly, so session tokens stay server-side (see lib/auth/session.ts).

const API_BASE_URL = process.env.PERITUS_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let message = body;
    try {
      // Entitlement denials send a structured `detail` object (code, tier,
      // remedy, …) rather than a string — see EntitlementError.to_payload in
      // billing/domain.py. Only its `message` is prose fit for ApiError.
      const detail = JSON.parse(body).detail;
      message = typeof detail === "string" ? detail : (detail?.message ?? body);
    } catch {
      // not JSON — use raw body
    }
    throw new ApiError(res.status, message || res.statusText);
  }

  if (res.status === 204) return null;
  return res.json();
}
