"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

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

export default function ExpertDetailPage() {
  const params = useParams();
  const slug = params.slug as string;

  const [expert, setExpert] = useState<ExpertSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    fetch(`/api/experts/${slug}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setExpert)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [slug]);

  if (loading) return <p className="status-line mt-3">Loading expert...</p>;
  if (error)
    return (
      <div className="error-box mt-3">
        Could not load expert: {error}
      </div>
    );
  if (!expert) return null;

  return (
    <main>
      <p className="small muted">
        <Link href="/experts">← All experts</Link>
      </p>

      <h1 style={{ marginTop: "1.5rem" }}>{expert.topic}</h1>
      <p className="muted mt-1">{expert.description}</p>

      <div className="mt-2" style={{ fontSize: "0.875rem", color: "var(--text-muted)" }}>
        <span className={`badge ${expert.status}`}>{expert.status}</span>
        &nbsp;&nbsp;
        {expert.source_count} sources &middot; {expert.node_count} nodes &middot;{" "}
        {expert.relation_count} relations
        &nbsp;&middot;&nbsp;
        Built {new Date(expert.created_at).toLocaleDateString()}
      </div>

      <div style={{ marginTop: "3rem", borderTop: "1px solid #ccc", paddingTop: "2rem" }}>
        <h2>What would you like to do?</h2>

        <div className="col" style={{ marginTop: "1.5rem", gap: "1.25rem" }}>
          <div>
            <Link href={`/chat/${slug}`} style={{ fontWeight: 700, fontSize: "1.05rem" }}>
              Start a conversation →
            </Link>
            <p className="muted small mt-1">
              Open-ended tutoring session. Ask questions, request explanations,
              take quizzes, explore concepts.
            </p>
          </div>
          <div>
            <Link href={`/course/${slug}`} style={{ fontWeight: 700, fontSize: "1.05rem" }}>
              Generate a course →
            </Link>
            <p className="muted small mt-1">
              Get a structured, multi-module course at beginner, intermediate,
              advanced, or custom difficulty.
            </p>
          </div>
        </div>
      </div>

      <div style={{ marginTop: "3rem", borderTop: "1px solid #ccc", paddingTop: "2rem" }}>
        <h2>Knowledge Graph Summary</h2>
        <table style={{ marginTop: "1rem", fontSize: "0.9rem", borderCollapse: "collapse", width: "auto" }}>
          <tbody>
            {[
              ["Slug", expert.slug],
              ["Sources ingested", String(expert.source_count)],
              ["Graph nodes", String(expert.node_count)],
              ["Graph relations", String(expert.relation_count)],
              ["Pinecone namespace", `peritus-${expert.slug}`],
              ["Storage path", `./storage/peritus/${expert.slug}`],
            ].map(([k, v]) => (
              <tr key={k}>
                <td style={{ paddingRight: "2rem", color: "var(--text-muted)", paddingBottom: "0.4rem" }}>
                  {k}
                </td>
                <td style={{ paddingBottom: "0.4rem" }}>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
