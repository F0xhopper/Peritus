"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Difficulty = "beginner" | "intermediate" | "advanced" | "custom";

interface ExpertSummary {
  slug: string;
  topic: string;
  status: string;
}

export default function CoursePage() {
  const params = useParams();
  const slug = params.slug as string;

  const [expert, setExpert] = useState<ExpertSummary | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty>("intermediate");
  const [focus, setFocus] = useState("");
  const [courseMarkdown, setCourseMarkdown] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const courseRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`/api/experts/${slug}`)
      .then((r) => r.json())
      .then(setExpert)
      .catch(() => setError("Could not load expert."));
  }, [slug]);

  async function generateCourse() {
    setGenerating(true);
    setCourseMarkdown("");
    setError(null);
    setStarted(true);

    try {
      const res = await fetch("/api/courses/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expert_slug: slug,
          difficulty,
          focus: focus.trim() || undefined,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      if (!reader) throw new Error("No response stream.");

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        buffer += chunk;
        setCourseMarkdown(buffer);
        setTimeout(() => {
          courseRef.current?.scrollTo({
            top: courseRef.current.scrollHeight,
            behavior: "smooth",
          });
        }, 50);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  return (
    <main>
      <p className="small muted">
        <Link href={`/experts/${slug}`}>← {expert?.topic || slug}</Link>
      </p>

      <h1 style={{ marginTop: "1.5rem" }}>
        Generate Course{expert?.topic ? `: ${expert.topic}` : ""}
      </h1>

      {!started && (
        <div style={{ marginTop: "2rem" }}>
          <p className="muted">
            Choose a difficulty level and optional focus area, then generate
            your course. The expert will draw on its full knowledge graph to
            produce a structured, multi-module curriculum.
          </p>

          <div className="col" style={{ marginTop: "2rem", gap: "1.25rem" }}>
            <div>
              <label
                htmlFor="difficulty"
                style={{ fontWeight: 700, display: "block", marginBottom: "0.5rem" }}
              >
                Difficulty
              </label>
              <select
                id="difficulty"
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value as Difficulty)}
              >
                <option value="beginner">Beginner (4 modules, gentle introduction)</option>
                <option value="intermediate">Intermediate (6 modules, technical depth)</option>
                <option value="advanced">Advanced (8 modules, research-level)</option>
                <option value="custom">Custom focus area</option>
              </select>
            </div>

            {difficulty === "custom" && (
              <div>
                <label
                  htmlFor="focus"
                  style={{ fontWeight: 700, display: "block", marginBottom: "0.5rem" }}
                >
                  Custom focus area
                </label>
                <input
                  id="focus"
                  type="text"
                  value={focus}
                  onChange={(e) => setFocus(e.target.value)}
                  placeholder="e.g. practical applications in finance, mathematical foundations..."
                />
              </div>
            )}

            <div>
              <button
                className="primary"
                onClick={generateCourse}
                disabled={generating}
              >
                Generate Course →
              </button>
            </div>
          </div>
        </div>
      )}

      {error && <div className="error-box mt-3">{error}</div>}

      {started && (
        <div style={{ marginTop: "2rem" }}>
          {generating && !courseMarkdown && (
            <p className="status-line">Generating course...</p>
          )}

          {courseMarkdown && (
            <>
              <div
                style={{
                  marginBottom: "1.5rem",
                  display: "flex",
                  gap: "1rem",
                  alignItems: "center",
                  borderBottom: "1px solid #ccc",
                  paddingBottom: "1rem",
                }}
              >
                <span className="small muted">
                  {difficulty} &middot; {expert?.topic}
                  {focus ? ` &middot; ${focus}` : ""}
                  {generating ? " · generating..." : " · complete"}
                </span>
                {!generating && (
                  <button
                    onClick={() => {
                      setStarted(false);
                      setCourseMarkdown("");
                    }}
                    style={{ fontSize: "0.8rem" }}
                  >
                    Generate again
                  </button>
                )}
                {!generating && (
                  <Link
                    href={`/chat/${slug}`}
                    style={{ fontSize: "0.85rem" }}
                  >
                    Ask follow-up questions →
                  </Link>
                )}
              </div>

              <div ref={courseRef} className="course-content prose">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {courseMarkdown}
                </ReactMarkdown>
                {generating && (
                  <span style={{ opacity: 0.4 }}>▋</span>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </main>
  );
}
