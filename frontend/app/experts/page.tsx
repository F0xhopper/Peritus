"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface ExpertSummary {
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

export default function ExpertsPage() {
  const [experts, setExperts] = useState<ExpertSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/experts")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setExperts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main>
      <h1>My Experts</h1>
      <p className="muted mt-1">
        All domain experts you have built. Click one to view, generate a
        course, or start a conversation.
      </p>

      {loading && <p className="status-line mt-3">Loading experts...</p>}

      {error && (
        <div className="error-box mt-3">
          Could not load experts: {error}
        </div>
      )}

      {!loading && !error && experts.length === 0 && (
        <p className="mt-4 muted">
          No experts yet.{" "}
          <Link href="/">Build your first expert →</Link>
        </p>
      )}

      {experts.length > 0 && (
        <ul className="expert-list">
          {experts.map((e) => (
            <li key={e.slug} className="expert-item">
              <div>
                <Link href={`/experts/${e.slug}`} className="expert-item-title">
                  {e.topic}
                </Link>
                <p className="expert-meta" style={{ marginTop: "0.25rem" }}>
                  {e.description
                    ? e.description.slice(0, 160) + (e.description.length > 160 ? "..." : "")
                    : "No description."}
                </p>
                <p className="expert-meta mt-1">
                  {e.source_count} sources &middot; {e.node_count} nodes &middot;{" "}
                  {e.relation_count} relations &middot;{" "}
                  {new Date(e.created_at).toLocaleDateString()}
                </p>
              </div>
              <div style={{ flexShrink: 0 }}>
                <span className={`badge ${e.status}`}>{e.status}</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4">
        <Link href="/">← Build a new expert</Link>
      </div>
    </main>
  );
}
