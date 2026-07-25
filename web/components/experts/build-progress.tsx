"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckIcon, TriangleAlertIcon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { StatusDot } from "@/components/experts/status-dot";
import { streamBuildEvents, ChatStreamError } from "@/lib/api/sse";
import { cn } from "@/lib/utils";
import {
  BUILD_STAGES,
  type BuildEvent,
  type BuildStage,
  type BuildStatus,
  type ExpertStatus,
} from "@/lib/api/types";

// Live view of a durable build.
//
// The whole design leans on one backend guarantee: every event is persisted
// with a monotonic `seq`, and `?after=<seq>` replays everything above it. So
// this does not need to be a fragile long-lived socket. It opens the stream at
// `after=0` (replaying the build so far, which is what makes a refresh
// mid-build show full history), and on an unexpected close it reconnects from
// the last `seq` it saw. Nothing is lost in the gap, and no event arrives
// twice.
//
// The build itself is entirely unaffected by any of this — closing the tab
// does not cancel it. Only the Cancel button does.

const RECONNECT_DELAY_MS = 2000;

type Phase = "connecting" | "running" | "done" | "error" | "cancelled";

interface State {
  phase: Phase;
  /** Stage names already finished, in completion order. */
  completed: BuildStage[];
  current: BuildStage | null;
  /** Human lines for the log tail, newest last. */
  log: string[];
  message: string | null;
  attempt: number | null;
  maxAttempts: number | null;
  counts: { sources?: number; chunks?: number; nodes?: number; edges?: number };
}

/** Start from what the server already knows, so the first paint is honest
 * about a finished build instead of claiming one is starting. */
function seedState(status: ExpertStatus, error: string | null): State {
  if (status === "ready") {
    return { ...INITIAL, phase: "done", completed: [...BUILD_STAGES] };
  }
  if (status === "failed") {
    return { ...INITIAL, phase: "error", message: error };
  }
  return INITIAL;
}

const INITIAL: State = {
  phase: "connecting",
  completed: [],
  current: null,
  log: [],
  message: null,
  attempt: null,
  maxAttempts: null,
  counts: {},
};

export function BuildProgress({
  slug,
  topic,
  initialStatus,
  initialError,
}: {
  slug: string;
  topic: string;
  /** The expert's status at server-render time. */
  initialStatus: ExpertStatus;
  /** The expert's stored `error`, shown until the job's own status arrives. */
  initialError: string | null;
}) {
  const router = useRouter();

  // Seeded from the server-rendered status rather than always starting at
  // "connecting". Replaying a finished build takes a second or two, and during
  // it a page that assumes "live" offers a Cancel button for a build that
  // ended days ago — an action that can only ever 409.
  const seededTerminal = initialStatus === "ready" || initialStatus === "failed";
  const [state, setState] = React.useState<State>(() =>
    seedState(initialStatus, initialError),
  );
  const [cancelling, setCancelling] = React.useState(false);

  // Held in a ref, not state: the reconnect loop reads it after awaits, and a
  // stale closure over a state value would restart the stream from an old
  // cursor and replay events the user has already seen.
  const cursor = React.useRef(0);

  React.useEffect(() => {
    const controller = new AbortController();
    let cancelledByUnmount = false;

    async function run() {
      while (!cancelledByUnmount) {
        try {
          const stream = streamBuildEvents(slug, cursor.current, controller.signal);
          for await (const event of stream) {
            if (typeof event.seq === "number") cursor.current = event.seq;
            setState((prev) => reduce(prev, event));
            if (isTerminal(event.type)) return;
          }
          // Stream closed without a terminal event. That is not necessarily a
          // dropped connection: a job can die without ever appending a
          // terminal event — a worker whose heartbeat times out has its
          // retries exhausted by the *queue*, and only `job_status` records
          // it. So the job's own status is the authority on how this ended,
          // not the absence of an event.
          const status = await fetchJobStatus(slug);
          if (status && status.job_status !== "queued" && status.job_status !== "running") {
            setState((prev) => applyJobStatus(prev, status));
            return;
          }
          if (status === null) return; // no job to wait for
        } catch (err) {
          if (controller.signal.aborted) return;
          if (err instanceof ChatStreamError && err.status === 404) {
            setState((prev) => ({
              ...prev,
              phase: "error",
              message: "No build has been run for this expert.",
            }));
            return;
          }
          // Anything else is treated as a dropped connection, which the
          // durable log makes safe to retry from the cursor.
        }
        if (cancelledByUnmount) return;
        await sleep(RECONNECT_DELAY_MS);
      }
    }

    void run();
    return () => {
      cancelledByUnmount = true;
      controller.abort();
    };
  }, [slug]);

  // A finished build changes the sidebar (the "building now" row disappears)
  // and the expert's own pages, both rendered on the server.
  React.useEffect(() => {
    if (state.phase === "done" || state.phase === "cancelled") router.refresh();
  }, [state.phase, router]);

  async function onCancel() {
    setCancelling(true);
    try {
      const res = await fetch(`/api/experts/${encodeURIComponent(slug)}/build/cancel`, {
        method: "POST",
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        // 409 means it finished first — not worth an error banner.
        setState((prev) => ({
          ...prev,
          message: res.status === 409 ? "The build already finished." : payload.error,
        }));
      }
      // The success path needs no local update: cancelling appends a terminal
      // `cancelled` event, which arrives on the stream we are already reading.
    } catch {
      setState((prev) => ({ ...prev, message: "Could not reach the server." }));
    } finally {
      setCancelling(false);
    }
  }

  // Never offered for a build that had already finished when the page loaded:
  // the replay walks back through "running" on its way to the real outcome,
  // and Cancel must not blink into existence during that.
  const live =
    !seededTerminal && (state.phase === "connecting" || state.phase === "running");

  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <Summary
        state={state}
        topic={topic}
        slug={slug}
        initiallyTerminal={seededTerminal}
      />

      <ol className="flex flex-col gap-0">
        {BUILD_STAGES.map((stage) => (
          <StageRow
            key={stage}
            stage={stage}
            done={state.completed.includes(stage)}
            active={state.current === stage && !seededTerminal}
          />
        ))}
      </ol>

      {state.log.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-eyebrow text-muted-foreground">Activity</p>
          {/* Newest first so the interesting end is the end you can see
              without scrolling a box that grows under you. */}
          <ul className="flex max-h-64 flex-col gap-1 overflow-y-auto font-mono text-xs text-muted-foreground">
            {[...state.log].reverse().map((line, i) => (
              <li key={`${state.log.length - i}-${line}`}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {live ? (
        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={onCancel} disabled={cancelling}>
            {cancelling ? <Spinner /> : <XIcon />}
            Cancel build
          </Button>
          <p className="text-sm text-muted-foreground">
            The build keeps running if you leave — only this stops it.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function Summary({
  state,
  topic,
  slug,
  initiallyTerminal,
}: {
  state: State;
  topic: string;
  slug: string;
  initiallyTerminal: boolean;
}) {
  if (state.phase === "done") {
    const { sources, chunks, nodes } = state.counts;
    return (
      <Banner icon={<CheckIcon className="size-4" />} title={`${topic} is ready.`}>
        <p className="text-sm text-muted-foreground">
          {sources !== undefined
            ? `${sources.toLocaleString()} sources · ${chunks?.toLocaleString() ?? 0} chunks · ${nodes?.toLocaleString() ?? 0} graph nodes.`
            : "The build finished."}
        </p>
        <div className="mt-3 flex gap-2">
          <Button nativeButton={false} render={<Link href={`/experts/${slug}/chat`} />}>
            Start a chat
          </Button>
          <Button
            variant="outline"
            nativeButton={false}
            render={<Link href={`/experts/${slug}`} />}
          >
            View expert
          </Button>
        </div>
      </Banner>
    );
  }

  if (state.phase === "error" || state.phase === "cancelled") {
    return (
      <Banner
        icon={<TriangleAlertIcon className="size-4" />}
        title={state.phase === "cancelled" ? "Build cancelled." : "Build failed."}
      >
        <p className="text-sm text-muted-foreground">
          {state.message ?? "No further detail was reported."}
        </p>
        <div className="mt-3 flex gap-2">
          <Button variant="outline" nativeButton={false} render={<Link href="/experts/new" />}>
            Start another build
          </Button>
          <Button
            variant="ghost"
            nativeButton={false}
            render={<Link href={`/experts/${slug}`} />}
          >
            View expert
          </Button>
        </div>
      </Banner>
    );
  }

  return (
    <Banner
      icon={<StatusDot status="building" />}
      title={state.current ? STAGE_LABELS[state.current] : "Starting the build…"}
    >
      <p className="text-sm text-muted-foreground">
        {initiallyTerminal
          ? "Replaying this expert's last build log."
          : "Building in the background. This page can be closed and reopened."}
        {state.attempt && state.attempt > 1
          ? ` Attempt ${state.attempt} of ${state.maxAttempts}.`
          : ""}
      </p>
      {state.message ? (
        <p className="mt-2 text-sm text-foreground">{state.message}</p>
      ) : null}
    </Banner>
  );
}

function Banner({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-3 rounded-lg border border-border bg-muted/30 p-4">
      <span className="mt-0.5 flex shrink-0 items-center">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="font-serif text-[1.0625rem] font-medium">{title}</p>
        {children}
      </div>
    </div>
  );
}

const STAGE_LABELS: Record<BuildStage, string> = {
  plan: "Drafting the research plan",
  discover: "Discovering sources",
  validate: "Validating sources",
  chunk: "Chunking and embedding",
  graph: "Extracting the concept graph",
  resolve: "Resolving duplicate entities",
  persona: "Generating the persona",
};

function StageRow({
  stage,
  done,
  active,
}: {
  stage: BuildStage;
  done: boolean;
  active: boolean;
}) {
  return (
    <li
      className={cn(
        "flex items-center gap-3 border-b border-border/60 py-2.5 text-sm last:border-b-0",
        !done && !active && "text-muted-foreground/50",
      )}
    >
      <span className="flex size-4 shrink-0 items-center justify-center">
        {active ? (
          <Spinner className="size-3.5" />
        ) : done ? (
          <CheckIcon className="size-3.5" />
        ) : (
          <span aria-hidden className="size-1.5 rounded-full bg-current" />
        )}
      </span>
      <span className={cn(active && "text-foreground")}>{STAGE_LABELS[stage]}</span>
      <span className="sr-only">
        {done ? " — complete" : active ? " — in progress" : " — pending"}
      </span>
    </li>
  );
}

/** Fold one event into the view. Pure, so replaying a log from `after=0`
 * produces exactly the state a live viewer would have reached. */
function reduce(prev: State, event: BuildEvent): State {
  switch (event.type) {
    case "build_started":
      // A retry re-emits this. The stage checklist has to rewind with it, or
      // attempt 2 would appear to start halfway through attempt 1's progress.
      return {
        ...prev,
        phase: "running",
        current: null,
        completed: [],
        attempt: event.attempt,
        maxAttempts: event.max_attempts,
      };

    case "discovery_started":
      return log(prev, `Discovering across ${event.active.length} fetchers.`);

    case "fetcher_done":
      return log(
        prev,
        event.skipped
          ? `${event.name}: skipped${event.reason ? ` — ${event.reason}` : ""}.`
          : `${event.name}: ${event.count} candidates from ${event.queries} ${
              event.queries === 1 ? "query" : "queries"
            }.`,
      );

    case "triage_done":
      return log(
        prev,
        `Triaged ${event.candidates} candidates → ${event.ranked} ranked (budget ${event.budget}).`,
      );

    case "fetch_done":
      return log(prev, `Fetched ${event.fetched} of ${event.budget} sources.`);

    case "stage": {
      const name = event.name as BuildStage;
      if (!BUILD_STAGES.includes(name)) return { ...prev, phase: "running" };
      // Everything before this stage in the canonical order is finished —
      // more robust than trusting a "stage done" event that isn't emitted for
      // every stage.
      const index = BUILD_STAGES.indexOf(name);
      return {
        ...prev,
        phase: "running",
        current: name,
        completed: BUILD_STAGES.slice(0, index),
      };
    }

    case "plan_ready":
      return log(
        prev,
        `Research plan ready — ${event.key_concepts.length} target concepts.`,
      );

    case "snowball_done":
      return log(prev, `Snowball search added ${event.added} sources.`);

    case "source_validated":
      return log(
        prev,
        `${event.passed ? "Kept" : "Dropped"}: ${truncate(event.title)} (Q:${event.q.toFixed(1)} R:${event.r.toFixed(1)})${
          !event.passed && event.drop_reason ? ` — ${event.drop_reason}` : ""
        }`,
      );

    case "validate_done":
      return log(prev, `Validation done — ${event.passed} kept, ${event.dropped} dropped.`);

    case "source_ingested":
      return log(
        prev,
        `Ingested ${truncate(event.title)} — ${event.chunks} chunks (${event.total_chunks} total).`,
      );

    case "graph_batch_done":
      return log(prev, `Graph batch — ${event.labels ?? 0} labels, ${event.edges ?? 0} edges.`);

    case "resolve_progress":
    case "entities_resolved":
      return log(prev, `Merged ${event.merged} duplicate entities.`);

    case "coverage_gaps":
      return log(prev, `Coverage gaps: ${event.gaps.join(", ")}`);

    case "persona_ready":
      return log(prev, `Persona ready — ${event.name}.`);

    case "retry":
      return {
        ...log(prev, `Attempt ${event.attempt} failed, retrying.`),
        attempt: event.attempt,
        message: event.message ?? null,
      };

    case "done":
      return {
        ...prev,
        phase: "done",
        current: null,
        completed: [...BUILD_STAGES],
        counts: {
          sources: event.source_count,
          chunks: event.chunk_count,
          nodes: event.node_count,
          edges: event.edge_count,
        },
      };

    case "error":
      return { ...prev, phase: "error", current: null, message: event.message };

    case "cancelled":
      return { ...prev, phase: "cancelled", current: null, message: event.message };

    default:
      return prev;
  }
}

/** Bounded so a pro build's thousands of source events can't grow the DOM
 * without limit over a long-running page. */
const MAX_LOG_LINES = 200;

function log(prev: State, line: string): State {
  const next = [...prev.log, line];
  return {
    ...prev,
    phase: "running",
    log: next.length > MAX_LOG_LINES ? next.slice(-MAX_LOG_LINES) : next,
  };
}

function truncate(text: string, max = 70): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function isTerminal(type: BuildEvent["type"]): boolean {
  return type === "done" || type === "error" || type === "cancelled";
}

/** The job's own record of how it ended. `null` means there is no job (404) or
 * the request failed — both "stop asking", neither "it succeeded". */
async function fetchJobStatus(slug: string): Promise<BuildStatus | null> {
  try {
    const res = await fetch(`/api/experts/${encodeURIComponent(slug)}/build/status`);
    if (!res.ok) return null;
    return (await res.json()) as BuildStatus;
  } catch {
    return null;
  }
}

/** Resolve a stream that ended without a terminal event, using `job_status`.
 *
 * Treating "the job stopped" as "the build succeeded" is the bug this exists
 * to prevent: a heartbeat-timeout failure leaves `job_status: "failed"` with
 * no `error` event behind it, and the page would otherwise announce a failed
 * expert as ready and offer to chat with it. */
function applyJobStatus(prev: State, status: BuildStatus): State {
  switch (status.job_status) {
    case "succeeded":
      return { ...prev, phase: "done", current: null, completed: [...BUILD_STAGES] };
    case "cancelled":
      return {
        ...prev,
        phase: "cancelled",
        current: null,
        message: status.last_error ?? "The build was cancelled.",
      };
    case "failed":
      return {
        ...prev,
        phase: "error",
        current: null,
        message:
          status.last_error ??
          `The build stopped after ${status.attempts} of ${status.max_attempts} attempts.`,
      };
    default:
      return prev;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
