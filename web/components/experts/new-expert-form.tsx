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
  // Every source starts on. The old default was an empty set that the backend
  // read as "all of them", which is the same build — but a row of unchecked
  // boxes says the opposite, so people checked two, narrowed a build they
  // meant to leave wide, and never saw the ones they'd switched off. Showing
  // the true default and letting it be narrowed by unchecking is the same
  // control, stated honestly.
  const [sources, setSources] = React.useState<Set<Fetcher>>(
    // Lazy init: `new Set(FETCHERS)` as a bare argument would rebuild the set
    // on every keystroke in the topic field and throw it away.
    () => new Set(FETCHERS),
  );
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const allSelected = sources.size === FETCHERS.length;
  const noneSelected = sources.size === 0;

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
    if (pending || noneSelected) return;

    setError(null);
    setPending(true);
    try {
      const res = await fetch("/api/experts/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: topic.trim(),
          tier,
          // Everything checked is sent as null, not as the full list. They are
          // not the same request: an explicit allowlist also *guarantees* each
          // named fetcher a slice of the budget (`_build_fetchers` floors its
          // weight at 1.0), so posting all nine would force Reddit into a
          // pharmacology build the planner had rightly zeroed out. Null keeps
          // every fetcher eligible and lets the planner weight them — which is
          // exactly what "all sources" means here.
          sources: allSelected ? null : [...sources],
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
        {/* The legend stays the fieldset's first child — a <legend> that isn't
            is just a styled block, and the group loses its accessible name. So
            the bulk control rides with the help text instead. */}
        <legend className="mb-1 text-eyebrow text-muted-foreground">
          Sources
        </legend>
        <div className="mb-2 flex items-start justify-between gap-4">
          <p className="text-sm text-muted-foreground">
            All sources are on, and the research planner decides how much of the
            budget each one earns. Switch some off to hold the build to the rest
            — a narrowed list also guarantees every source left on it a share.
          </p>
          {/* One control, two directions: "all on" and "all off" are the only
              places a bulk action can go, and a pair of buttons would leave one
              of them permanently in a no-op state. */}
          <button
            type="button"
            onClick={() =>
              setSources(allSelected ? new Set() : new Set(FETCHERS))
            }
            className="shrink-0 rounded-lg text-xs text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
          >
            {allSelected ? "Clear all" : "Select all"}
          </button>
        </div>
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
                    // Off is now a decision rather than a starting point, so it
                    // gets its own mark. The theme is monochrome — a dashed
                    // edge is the "excluded" signal a color would otherwise
                    // carry, and it survives being read at a glance.
                    : "border-dashed border-border text-muted-foreground/60 hover:bg-muted/25",
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
        {/* Nothing checked can't be sent: the backend reads an empty list as
            "every fetcher", so a build started from a blank row would use the
            sources the user had just switched off. Blocked here rather than
            silently reinterpreted. */}
        {noneSelected ? (
          <p className="text-sm text-foreground">
            Leave at least one source on — a build with none has nothing to
            read.
          </p>
        ) : null}
      </fieldset>

      {error ? (
        <p role="alert" className="text-sm text-foreground">
          {error}
        </p>
      ) : null}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={pending || !topic.trim() || noneSelected}>
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
