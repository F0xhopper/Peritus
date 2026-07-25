"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Loader2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { FETCHERS, type ExpertTier, type Fetcher } from "@/lib/api/types";

// The build form. Submits to /api/experts/build, which enqueues the job and
// answers with the slug to watch, then hands off to the progress page.
//
// Deliberately not react-hook-form: three fields, one of which is a checkbox
// grid, and the only validation that matters ("does this slugify to anything")
// is re-checked server-side anyway. A resolver and a schema would be more
// machinery than the form has state.

/** Copy is derived from `_TIER_DEFAULTS` in experts/domain.py — these are the
 * real multipliers and retrieval widths, not marketing tiers. */
const TIERS: { value: ExpertTier; label: string; detail: string }[] = [
  {
    value: "lite",
    label: "Lite",
    detail: "Half the sources. Fast and narrow — good for trying a topic out.",
  },
  {
    value: "standard",
    label: "Standard",
    detail: "The baseline corpus and retrieval width. Right for most experts.",
  },
  {
    value: "pro",
    label: "Pro",
    detail: "Double the sources, wider retrieval, two-hop graph. Slow and thorough.",
  },
];

/** Human labels for the fetcher ids in `_build_fetchers`. */
const FETCHER_LABELS: Record<Fetcher, string> = {
  wikipedia: "Wikipedia",
  gutenberg: "Gutenberg",
  arxiv: "arXiv",
  pdf: "PDFs",
  youtube: "YouTube",
  exa: "Exa search",
  web: "Web",
  reddit: "Reddit",
  thought_leaders: "Thought leaders",
};

export function NewExpertForm() {
  const router = useRouter();
  const [topic, setTopic] = React.useState("");
  const [tier, setTier] = React.useState<ExpertTier>("standard");
  const [sources, setSources] = React.useState<Set<Fetcher>>(new Set());
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const toggleSource = (name: Fetcher) => {
    setSources((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;

    setError(null);
    setPending(true);
    try {
      const res = await fetch("/api/experts/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: topic.trim(),
          tier,
          // Empty set means "no opinion", which the backend reads as "every
          // fetcher" — not "no fetchers".
          sources: sources.size > 0 ? [...sources] : null,
        }),
      });

      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(payload.error ?? "The build could not be started.");
        setPending(false);
        return;
      }

      // Stays pending through the navigation: re-enabling the button here
      // would let an impatient second click enqueue nothing (the backend
      // attaches to the in-flight job) while looking like it did something.
      router.push(`/experts/${payload.slug}/build`);
      // The dashboard layout fetched its expert list before this expert
      // existed, and a client navigation reuses that cached layout — so
      // without this the breadcrumb falls back to the slug and the sidebar's
      // "building now" row never appears until a manual reload.
      router.refresh();
    } catch {
      setError("Could not reach the server. Check your connection and retry.");
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex max-w-2xl flex-col gap-8">
      <div className="flex flex-col gap-2">
        <Label htmlFor="topic">Topic</Label>
        <Input
          id="topic"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Stoic philosophy"
          maxLength={300}
          autoFocus
          required
          aria-describedby="topic-help"
        />
        <p id="topic-help" className="text-sm text-muted-foreground">
          What the expert should know. This becomes its name and drives the
          research plan, so a subject reads better than a question.
        </p>
      </div>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-3 text-eyebrow text-muted-foreground">
          Build depth
        </legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {TIERS.map((option) => {
            const selected = tier === option.value;
            return (
              <label
                key={option.value}
                className={cn(
                  "flex cursor-pointer flex-col gap-1.5 rounded-lg border p-3 transition-colors",
                  selected
                    ? "border-foreground/40 bg-muted/50"
                    : "border-border hover:bg-muted/25",
                )}
              >
                <span className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="tier"
                    value={option.value}
                    checked={selected}
                    onChange={() => setTier(option.value)}
                    className="sr-only"
                  />
                  {/* The ring is the radio: a native control here would be
                      restyled to nothing anyway, and the label is the hit
                      target either way. */}
                  <span
                    aria-hidden
                    className={cn(
                      "size-2 rounded-full ring-1 transition-colors",
                      selected
                        ? "bg-foreground ring-foreground"
                        : "bg-transparent ring-muted-foreground/50",
                    )}
                  />
                  <span className="font-medium">{option.label}</span>
                </span>
                <span className="text-xs leading-relaxed text-muted-foreground">
                  {option.detail}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 text-eyebrow text-muted-foreground">
          Sources
        </legend>
        <p className="mb-2 text-sm text-muted-foreground">
          Leave all unchecked to let the research planner choose. Checking any
          restricts the build to those fetchers and guarantees each one a share
          of the budget.
        </p>
        <div className="flex flex-wrap gap-2">
          {FETCHERS.map((name) => {
            const checked = sources.has(name);
            return (
              <label
                key={name}
                className={cn(
                  "cursor-pointer rounded-lg border px-3 py-1.5 text-sm transition-colors",
                  checked
                    ? "border-foreground/40 bg-muted/60 text-foreground"
                    : "border-border text-muted-foreground hover:bg-muted/25",
                )}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleSource(name)}
                  className="sr-only"
                />
                {FETCHER_LABELS[name]}
              </label>
            );
          })}
        </div>
      </fieldset>

      {error ? (
        <p role="alert" className="text-sm text-foreground">
          {error}
        </p>
      ) : null}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={pending || !topic.trim()}>
          {pending ? <Loader2Icon className="animate-spin" /> : null}
          {pending ? "Starting build…" : "Start build"}
        </Button>
        <p className="text-sm text-muted-foreground">
          Builds run in the background — you can leave this page.
        </p>
      </div>
    </form>
  );
}
