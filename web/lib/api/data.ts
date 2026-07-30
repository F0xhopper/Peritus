import "server-only";
import { redirect } from "next/navigation";
import { ApiError } from "@/lib/api/server";
import { proxyJson, NotAuthenticatedError } from "@/lib/api/proxy";
import type {
  CorpusSource,
  ConversationDetail,
  ConversationSummary,
  CoverageReport,
  CreditState,
  LedgerEntry,
  ExpertDetail,
  ExpertGraph,
  ExpertSummary,
  User,
} from "@/lib/api/types";

// Fetchers for server components. These call FastAPI directly through the
// proxy helper — server components don't need the /api/* hop, which exists for
// the browser.
//
// An expired session reaches here as NotAuthenticatedError: the proxy
// middleware only checks that a session cookie *exists*, so a cookie whose
// refresh token has died passes the gate and fails at fetch time. Pages send
// those users to login rather than rendering a crash.

async function fetchOrLogin<T>(fetcher: () => Promise<T>): Promise<T> {
  try {
    return await fetcher();
  } catch (err) {
    // redirect() signals via a thrown control-flow error, so it must be raised
    // outside the catch that swallowed the auth failure.
    if (err instanceof NotAuthenticatedError) redirect("/login");
    throw err;
  }
}

export async function getCurrentUser(): Promise<User> {
  return fetchOrLogin(() => proxyJson<User>("/auth/me"));
}

export async function getExperts(): Promise<ExpertSummary[]> {
  return fetchOrLogin(() => proxyJson<ExpertSummary[]>("/experts"));
}

export async function getExpert(slug: string): Promise<ExpertDetail | null> {
  return fetchOrLogin(async () => {
    try {
      return await proxyJson<ExpertDetail>(`/experts/${encodeURIComponent(slug)}`);
    } catch (err) {
      // 404 covers both "no such expert" and "not yours" — the backend hides
      // the difference on purpose, and so does the page (notFound()).
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });
}

/** Every source in an expert's corpus. Owner-only upstream, so this 404s for
 * anyone else — the page already handles that via getExpert. */
export async function getExpertSources(slug: string): Promise<CorpusSource[]> {
  return fetchOrLogin(async () => {
    try {
      return await proxyJson<CorpusSource[]>(
        `/experts/${encodeURIComponent(slug)}/sources`,
      );
    } catch (err) {
      // A corpus the caller cannot manage simply has no manageable sources;
      // the panel renders empty rather than taking the whole page down.
      if (err instanceof ApiError && err.status === 404) return [];
      throw err;
    }
  });
}

export async function getExpertConversations(
  slug: string,
): Promise<ConversationSummary[]> {
  return fetchOrLogin(() =>
    proxyJson<ConversationSummary[]>(
      `/experts/${encodeURIComponent(slug)}/conversations`,
    ),
  );
}

export async function getRecentConversations(
  limit = 8,
): Promise<ConversationSummary[]> {
  return fetchOrLogin(() =>
    proxyJson<ConversationSummary[]>(`/conversations?limit=${limit}`),
  );
}

export async function getConversation(
  id: string,
): Promise<ConversationDetail | null> {
  return fetchOrLogin(async () => {
    try {
      return await proxyJson<ConversationDetail>(
        `/conversations/${encodeURIComponent(id)}`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });
}

/** Swallow fetch failures and return `fallback`, for chrome (sidebar, nav)
 * that should degrade to empty rather than error the whole page. */
export async function safely<T>(
  fetcher: () => Promise<T>,
  fallback: T,
): Promise<T> {
  try {
    return await fetcher();
  } catch (err) {
    // redirect() and notFound() signal by throwing; swallowing those would
    // strand an expired session on a half-rendered dashboard.
    if (isNextControlFlow(err)) throw err;
    return fallback;
  }
}

function isNextControlFlow(err: unknown): boolean {
  const digest = (err as { digest?: unknown } | null)?.digest;
  return typeof digest === "string" && digest.startsWith("NEXT_");
}

// ── audit surface ───────────────────────────────────────────────────────────
// See docs/audit-api.md. Every fetcher here is read-only; nothing under
// /audit mutates a corpus.

export async function getCoverage(slug: string): Promise<CoverageReport | null> {
  return fetchOrLogin(async () => {
    try {
      return await proxyJson<CoverageReport>(
        `/experts/${encodeURIComponent(slug)}/coverage`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });
}

export async function getExpertGraph(
  slug: string,
  limit?: number,
): Promise<ExpertGraph | null> {
  const qs = limit != null ? `?limit=${limit}` : "";
  return fetchOrLogin(async () => {
    try {
      return await proxyJson<ExpertGraph>(
        `/experts/${encodeURIComponent(slug)}/graph${qs}`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });
}

// ── credits ──────────────────────────────────────────────────────────────

export async function getCreditState(): Promise<CreditState> {
  return fetchOrLogin(() => proxyJson<CreditState>("/billing/me"));
}

export async function getCreditLedger(): Promise<LedgerEntry[]> {
  return fetchOrLogin(() => proxyJson<LedgerEntry[]>("/billing/ledger"));
}
