"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const [topic, setTopic] = useState("");
  const [building, setBuilding] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const progressRef = useRef<HTMLDivElement>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!topic.trim() || building) return;

    setBuilding(true);
    setProgress([]);
    setError(null);

    try {
      const res = await fetch("/api/experts/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: topic.trim() }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let slug = "";

      if (!reader) throw new Error("No response stream.");

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const text = decoder.decode(value);
        const lines = text.split("\n").filter((l) => l.startsWith("data: "));

        for (const line of lines) {
          const msg = line.replace(/^data: /, "");
          if (msg.startsWith("DONE slug=")) {
            slug = msg.replace("DONE slug=", "").trim();
          } else if (msg.startsWith("ERROR ")) {
            throw new Error(msg.replace("ERROR ", ""));
          } else {
            setProgress((prev) => [...prev, msg]);
            setTimeout(() => {
              progressRef.current?.scrollTo({
                top: progressRef.current.scrollHeight,
                behavior: "smooth",
              });
            }, 50);
          }
        }
      }

      if (slug) {
        router.push(`/experts/${slug}`);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setBuilding(false);
    }
  }

  return (
    <main>
      <h1>Build a Domain Expert</h1>
      <p className="muted mt-1">
        Enter any topic. Peritus will research it, build a knowledge graph, and
        create a persistent AI expert you can converse with and learn from.
      </p>

      <form onSubmit={handleSubmit} style={{ marginTop: "2.5rem" }}>
        <label
          htmlFor="topic"
          style={{ display: "block", fontWeight: 700, marginBottom: "0.5rem" }}
        >
          Topic
        </label>
        <div className="row">
          <input
            id="topic"
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Quantum Computing, Byzantine Fault Tolerance, Bayesian Statistics"
            disabled={building}
            autoFocus
          />
          <button
            type="submit"
            className="primary"
            disabled={building || !topic.trim()}
            style={{ whiteSpace: "nowrap" }}
          >
            {building ? "Building..." : "Build Expert →"}
          </button>
        </div>
      </form>

      {building && progress.length > 0 && (
        <div style={{ marginTop: "2rem" }}>
          <p className="small muted" style={{ marginBottom: "0.75rem" }}>
            Building knowledge base...
          </p>
          <div
            ref={progressRef}
            style={{
              maxHeight: "18rem",
              overflowY: "auto",
              borderLeft: "3px solid #ccc",
              paddingLeft: "1rem",
            }}
          >
            {progress.map((line, i) => (
              <div key={i} className="status-line">
                {line}
              </div>
            ))}
            {building && (
              <div className="status-line" style={{ opacity: 0.5 }}>
                working...
              </div>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="error-box" style={{ marginTop: "1.5rem" }}>
          Error: {error}
        </div>
      )}

      <div style={{ marginTop: "4rem", borderTop: "1px solid #ccc", paddingTop: "2rem" }}>
        <h2>What is Peritus?</h2>
        <p>
          <em>Peritus</em> (Latin: &ldquo;expert&rdquo;) builds a reusable, graph-grounded
          AI expert for any domain. Once built, your expert persists —
          you can generate structured courses at any difficulty level, or have
          an open-ended tutoring conversation with full knowledge graph context.
        </p>
        <h3>How it works</h3>
        <ol>
          <li>
            <strong>Research:</strong> Peritus discovers authoritative sources via
            Exa, ArXiv, and Firecrawl.
          </li>
          <li>
            <strong>Index:</strong> A PropertyGraphIndex is built with entity-relation
            triples, embedded with Voyage-3, and stored in Pinecone.
          </li>
          <li>
            <strong>Interact:</strong> Ask for a structured course or start a
            free-form tutoring conversation. Every answer is grounded in your
            expert&apos;s knowledge graph.
          </li>
        </ol>
      </div>
    </main>
  );
}
