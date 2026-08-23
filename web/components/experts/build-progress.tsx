"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeftIcon,
  CheckIcon,
  ChevronDownIcon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react";
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

type StageLogs = Record<BuildStage, string[]>;

interface State {
  phase: Phase;
  /** Stage names already finished, in completion order. */
  completed: BuildStage[];
  current: BuildStage | null;
  /** Human detail lines, grouped under whichever stage was active when the
   * event arrived — so the stream reads as "what happened during discovery"
   * rather than one undifferentiated feed. Newest last within each stage. */
  logs: StageLogs;
  /** Whichever stage was current when an `error` event landed — `current`
   * itself gets nulled so the pipeline rail stops animating it, but the rail
   * still needs to know which node to mark as the failure. */
  failedStage: BuildStage | null;
  message: string | null;
  attempt: number | null;
  maxAttempts: number | null;
  counts: { sources?: number; chunks?: number; nodes?: number; edges?: number };
}

function emptyLogs(): StageLogs {
  return Object.fromEntries(
    BUILD_STAGES.map((s) => [s, [] as string[]]),
  ) as unknown as StageLogs;
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
  logs: emptyLogs(),
  failedStage: null,
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
  const seededTerminal =
    initialStatus === "ready" || initialStatus === "failed";
  const [state, setState] = React.useState<State>(() =>
    seedState(initialStatus, initialError),
  );
  const [cancelling, setCancelling] = React.useState(false);
  const [expanded, setExpanded] = React.useState<Set<BuildStage>>(
    () => new Set(),
  );

  const toggleExpanded = (stage: BuildStage) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) next.delete(stage);
      else next.add(stage);
      return next;
    });
  };

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
          const stream = streamBuildEvents(
            slug,
            cursor.current,
            controller.signal,
          );
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
          if (
            status &&
            status.job_status !== "queued" &&
            status.job_status !== "running"
          ) {
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
      const res = await fetch(
        `/api/experts/${encodeURIComponent(slug)}/build/cancel`,
        {
          method: "POST",
        },
      );
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        // 409 means it finished first — not worth an error banner.
        setState((prev) => ({
          ...prev,
          message:
            res.status === 409 ? "The build already finished." : payload.error,
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
    !seededTerminal &&
    (state.phase === "connecting" || state.phase === "running");

  const terminal =
    state.phase === "done" ||
    state.phase === "error" ||
    state.phase === "cancelled";

  const stageStates = Object.fromEntries(
    BUILD_STAGES.map((stage) => [
      stage,
      stageState({
        stage,
        completed: state.completed,
        current: state.current,
        failedStage: state.failedStage,
        hasLines: state.logs[stage].length > 0,
        terminal,
        seededTerminal,
      }),
    ]),
  ) as Record<BuildStage, StageState>;

  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <Button
        variant="ghost"
        size="sm"
        nativeButton={false}
        // Not router.back(): a build page reached directly (a bookmark, a
        // shared link, a new tab) has no in-app history to go back to, and
        // router.back() then leaves the app entirely. The expert page is
        // always the correct destination — it's this page's own breadcrumb
        // parent.
        render={<Link href={`/experts/${slug}`} />}
        className="w-fit"
      >
        <ArrowLeftIcon />
        Back
      </Button>

      <PipelineRail states={stageStates} />

      <Summary
        state={state}
        topic={topic}
        slug={slug}
        initiallyTerminal={seededTerminal}
      />

      <ol className="flex flex-col gap-1">
        {BUILD_STAGES.map((stage) => (
          <StageRow
            key={stage}
            stage={stage}
            state={stageStates[stage]}
            lines={state.logs[stage]}
            expanded={expanded.has(stage)}
            onToggle={() => toggleExpanded(stage)}
          />
        ))}
      </ol>

      {/* A retry rewinds the checklist, so without this the "ran earlier" rows
          above look like a contradiction rather than the previous attempt's
          real work. */}
      {state.attempt && state.attempt > 1 ? (
        <p className="text-xs text-muted-foreground">
          Attempt {state.attempt} of {state.maxAttempts}. Stages marked “ran
          earlier” completed on a previous attempt.
        </p>
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
      <Banner
        icon={<CheckIcon className="size-4" />}
        title={`${topic} is ready.`}
      >
        <p className="text-sm text-muted-foreground">
          {sources !== undefined
            ? `${sources.toLocaleString()} sources · ${chunks?.toLocaleString() ?? 0} chunks · ${nodes?.toLocaleString() ?? 0} graph nodes.`
            : "The build finished."}
        </p>
        <div className="mt-3 flex gap-2">
          <Button
            nativeButton={false}
            render={<Link href={`/experts/${slug}/chat`} />}
          >
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
        title={
          state.phase === "cancelled" ? "Build cancelled." : "Build failed."
        }
      >
        <p className="text-sm text-muted-foreground">
          {state.message ?? "No further detail was reported."}
        </p>
        <div className="mt-3 flex gap-2">
          {/* Not "retry": this goes to the new-expert form, which builds a
              *different* expert. There is no rebuild-in-place action yet, and
              a button that reads like one would be a lie. */}
          <Button
            variant="outline"
            nativeButton={false}
            render={<Link href="/experts/new" />}
          >
            Build a new expert
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

  // Running / connecting: the rail above already carries the step-by-step
  // overview, so this is a compact readout of the one thing that's actually
  // changing right now — not a second hero competing with it.
  const stepIndex = state.current ? BUILD_STAGES.indexOf(state.current) : -1;
  const stageLines = state.current ? state.logs[state.current] : [];
  const latestLine = stageLines[stageLines.length - 1];

  return (
    <div className="flex flex-col items-center gap-1.5 py-1 text-center">
      <p className="flex items-center gap-2 font-serif text-lg font-medium">
        {state.current ? (
          <Spinner className="size-4" />
        ) : (
          <StatusDot status="building" />
        )}
        {state.current ? STAGE_LABELS[state.current] : "Starting the build…"}
      </p>
      <p className="text-sm text-muted-foreground">
        {stepIndex >= 0
          ? `Step ${stepIndex + 1} of ${BUILD_STAGES.length}`
          : "Connecting…"}
        {state.attempt && state.attempt > 1
          ? ` · Attempt ${state.attempt} of ${state.maxAttempts}`
          : ""}
        {/* No percentage exists to show — the pipeline reports counts, not
            progress — but "how long have I been here" is answerable exactly,
            and it is the question a ten-minute build actually raises. */}
        {!initiallyTerminal ? <Elapsed /> : null}
      </p>
      <p
        aria-live="polite"
        className="mt-1 min-h-5 max-w-md font-mono text-xs text-muted-foreground"
      >
        {latestLine ?? ""}
      </p>
      <p className="text-xs text-muted-foreground/70">
        {initiallyTerminal
          ? "Replaying this expert's last build log."
          : "Building in the background. This page can be closed and reopened."}
      </p>
      {state.message ? (
        <p className="mt-1 text-sm text-foreground">{state.message}</p>
      ) : null}
    </div>
  );
}

/** Time on this page, not build duration — the build may have been running
 * before the page opened, and the event log carries no timestamps to
 * reconstruct from. Worded as "watching for" so it never claims otherwise. */
function Elapsed() {
  const [seconds, setSeconds] = React.useState(0);

  // The clock is read in the effect, not during render: `Date.now()` in a
  // render body is an impure read that can drift between a render and its
  // replay.
  React.useEffect(() => {
    const start = Date.now();
    const id = window.setInterval(
      () => setSeconds(Math.floor((Date.now() - start) / 1000)),
      1000,
    );
    return () => window.clearInterval(id);
  }, []);

  if (seconds < 10) return null;
  const minutes = Math.floor(seconds / 60);
  return (
    <> · watching for {minutes > 0 ? `${minutes}m ` : ""}{seconds % 60}s</>
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
    <div className="flex gap-3 rounded-lg bg-muted/30 p-4">
      <span className="mt-0.5 flex shrink-0 items-center">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="font-serif text-[1.0625rem] font-medium">{title}</p>
        {children}
      </div>
    </div>
  );
}

/** What a stage is doing, as far as the event log can tell.
 *
 * The list used to know only done / active / failed / pending, and rendered
 * everything else as an unlit dot. That produced the one genuinely misleading
 * thing on this page: after a failed build, a stage holding thirty events
 * looked identical to a stage that never started — and a stage the build never
 * reached looked identical to one still waiting its turn. Both now say what
 * they are. `ran` is common on a retried build: attempt 1 gets several stages
 * in before it dies, attempt 2 resets the checklist, and those earlier events
 * are still real. */
type StageState = "done" | "active" | "failed" | "ran" | "skipped" | "pending";

function stageState({
  stage,
  completed,
  current,
  failedStage,
  hasLines,
  terminal,
  seededTerminal,
}: {
  stage: BuildStage;
  completed: BuildStage[];
  current: BuildStage | null;
  failedStage: BuildStage | null;
  hasLines: boolean;
  /** The build has stopped — nothing pending will ever start. */
  terminal: boolean;
  seededTerminal: boolean;
}): StageState {
  if (failedStage === stage) return "failed";
  if (current === stage && !seededTerminal) return "active";
  if (completed.includes(stage)) return "done";
  if (hasLines) return "ran";
  if (terminal) return "skipped";
  return "pending";
}

/** The short note beside a stage row, for the states whose glyph alone would
 * be ambiguous. Done/active/failed are already legible. */
const STAGE_STATE_NOTE: Partial<Record<StageState, string>> = {
  ran: "ran earlier",
  skipped: "not reached",
};

const STAGE_LABELS: Record<BuildStage, string> = {
  plan: "Drafting the research plan",
  discover: "Discovering sources",
  validate: "Validating sources",
  chunk: "Chunking and embedding",
  graph: "Extracting the concept graph",
  resolve: "Resolving duplicate entities",
  persona: "Generating the persona",
};

const SHORT_STAGE_LABELS: Record<BuildStage, string> = {
  plan: "Plan",
  discover: "Discover",
  validate: "Validate",
  chunk: "Chunk",
  graph: "Graph",
  resolve: "Resolve",
  persona: "Persona",
};

/** The at-a-glance overview: a CI-run-style rail of connected nodes, one per
 * stage. The vertical list below is where the detail lives — this is only
 * "where am I in the 7 steps," answerable without reading anything. */
function PipelineRail({ states }: { states: Record<BuildStage, StageState> }) {
  return (
    <ol className="relative flex items-start">
      {/* One continuous line from the first node's center to the last's —
          symmetric because every column below is an equal flex-1 share, so
          each node sits exactly 100% / (2 × 7 stages) in from its edge.
          Tailwind's scanner needs a literal class string, not a template
          built from BUILD_STAGES.length, so this is hand-computed and would
          need updating alongside BUILD_STAGES if a stage is ever added. */}
      <div
        aria-hidden
        className="absolute inset-x-[calc(100%/14)] top-3 h-px bg-border"
      />
      {BUILD_STAGES.map((stage) => {
        const state = states[stage];
        const lit = state === "done" || state === "active" || state === "failed";
        return (
          <li
            key={stage}
            className="relative flex flex-1 flex-col items-center gap-1.5"
          >
            <span
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full bg-background",
                !lit && "text-muted-foreground/50",
              )}
            >
              <StageGlyph state={state} className="size-4" />
            </span>
            <span
              className={cn(
                "hidden text-center text-[0.6875rem] text-muted-foreground sm:block",
                (state === "active" || state === "failed") && "text-foreground",
                !lit && "text-muted-foreground/50",
                // A stage the build never reached is struck through rather
                // than merely dim, so "didn't happen" is distinguishable from
                // "hasn't happened yet" at a glance.
                state === "skipped" && "line-through",
              )}
            >
              {SHORT_STAGE_LABELS[stage]}
            </span>
            {/* The labels are hidden below `sm`, so on a phone this is the
                only thing naming the stage at all. */}
            <span className="sr-only">
              {STAGE_LABELS[stage]} — {STAGE_STATE_SR[state]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

const STAGE_STATE_SR: Record<StageState, string> = {
  done: "complete",
  active: "in progress",
  failed: "failed here",
  ran: "ran on an earlier attempt",
  skipped: "not reached",
  pending: "pending",
};

/** One glyph per state, shared by the rail and the list so the two can never
 * disagree about what a stage is doing. */
function StageGlyph({
  state,
  className,
}: {
  state: StageState;
  className?: string;
}) {
  switch (state) {
    case "failed":
      return <TriangleAlertIcon className={cn(className, "text-foreground")} />;
    case "active":
      return <Spinner className={className} />;
    case "done":
      return <CheckIcon className={className} />;
    case "ran":
      // Ran but was never confirmed complete — a hollow ring against the solid
      // tick, which is the same "started, unfinished" distinction the graph
      // draws between a concept and a claim.
      return (
        <span
          aria-hidden
          className={cn(
            "size-2 rounded-full border border-current",
            className && "shrink-0",
          )}
        />
      );
    case "skipped":
      return (
        <span aria-hidden className="h-px w-2 bg-current" />
      );
    default:
      return <span aria-hidden className="size-1.5 rounded-full bg-current" />;
  }
}

function StageRow({
  stage,
  state,
  lines,
  expanded,
  onToggle,
}: {
  stage: BuildStage;
  state: StageState;
  /** Detail lines streamed while this stage was current. */
  lines: string[];
  /** Whether a finished stage's detail is toggled open. Ignored while active
   * — the active stage's detail is always visible, since that is the thing
   * being watched. */
  expanded: boolean;
  onToggle: () => void;
}) {
  const hasLines = lines.length > 0;
  const active = state === "active";
  const open = active || (hasLines && expanded);
  const lit = state === "done" || active || state === "failed";
  const note = STAGE_STATE_NOTE[state];

  return (
    <li className={cn("py-1", !lit && "text-muted-foreground/50")}>
      <button
        type="button"
        onClick={hasLines && !active ? onToggle : undefined}
        disabled={!hasLines || active}
        aria-expanded={hasLines ? open : undefined}
        className={cn(
          "flex w-full items-center gap-3 text-left text-sm outline-none",
          hasLines && !active && "cursor-pointer hover:text-foreground",
        )}
      >
        <span className="flex size-4 shrink-0 items-center justify-center">
          <StageGlyph state={state} className="size-3.5" />
        </span>
        <span
          className={cn(
            "flex-1",
            (active || state === "failed") && "text-foreground",
            state === "skipped" && "line-through",
          )}
        >
          {STAGE_LABELS[stage]}
        </span>
        {note ? (
          <span className="shrink-0 text-xs text-muted-foreground/70">
            {note}
          </span>
        ) : null}
        {hasLines ? (
          <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
            {lines.length} {lines.length === 1 ? "event" : "events"}
            {!active ? (
              <ChevronDownIcon
                aria-hidden
                className={cn(
                  "size-3.5 transition-transform",
                  open && "rotate-180",
                )}
              />
            ) : null}
          </span>
        ) : null}
        <span className="sr-only"> — {STAGE_STATE_SR[state]}</span>
      </button>
      {open ? (
        <ul className="mt-2 ml-7 flex max-h-40 flex-col gap-1 overflow-y-auto py-0.5 font-mono text-xs text-muted-foreground/80">
          {/* Newest first so the interesting end is the end you can see
              without scrolling a box that grows under you. */}
          {[...lines].reverse().map((line, i) => (
            <li key={`${lines.length - i}-${line}`}>{line}</li>
          ))}
        </ul>
      ) : null}
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
      // Prior stages' logs are kept (not cleared) — the retry line itself,
      // attached to whichever stage was active when it failed, marks the seam.
      return {
        ...prev,
        phase: "running",
        current: null,
        completed: [],
        failedStage: null,
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

    case "fetch_progress":
      return log(
        prev,
        `Fetching sources: ${event.fetched}/${event.budget} retrieved (${event.attempted} tried).`,
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
      return log(
        prev,
        `Validation done — ${event.passed} kept, ${event.dropped} dropped.`,
      );

    case "coverage_gaps":
      return log(prev, `Coverage gaps found for: ${event.gaps.join(", ")}.`);

    // Not a failure — the build continues — but the user should read this
    // before they trust the expert's answers, so it says what it means rather
    // than reporting a ratio.
    case "corpus_warning":
      return log(prev, `⚠ ${event.message}`);

    case "gapfill_done":
      return log(
        prev,
        event.added > 0
          ? `Gap-fill added ${event.added} source${event.added === 1 ? "" : "s"}.${
              event.still_uncovered.length
                ? ` Still uncovered: ${event.still_uncovered.join(", ")}.`
                : ""
            }`
          : `Gap-fill found nothing new for: ${event.still_uncovered.join(", ")}.`,
      );

    case "source_ingested":
      return log(
        prev,
        `Ingested ${truncate(event.title)} — ${event.chunks} chunks (${event.total_chunks} total).`,
      );

    case "chat_ready":
      return log(
        prev,
        `Chat-ready — ${event.sources} sources, ${event.chunks} chunks indexed.`,
      );

    case "graph_batch_done":
      return log(
        prev,
        `Graph batch — ${event.labels ?? 0} labels, ${event.edges ?? 0} edges.`,
      );

    case "graph_ready":
      return log(
        prev,
        `Graph ready — ${event.nodes} nodes, ${event.edges} edges.`,
      );

    case "resolve_progress":
    case "entities_resolved":
      return log(prev, `Merged ${event.merged} duplicate entities.`);

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
      return {
        ...prev,
        phase: "error",
        current: null,
        failedStage: prev.current,
        message: event.message,
      };

    case "cancelled":
      return {
        ...prev,
        phase: "cancelled",
        current: null,
        message: event.message,
      };

    default:
      return prev;
  }
}

/** Bounded per stage so a pro build's thousands of source events can't grow
 * the DOM without limit over a long-running page. */
const MAX_STAGE_LOG_LINES = 150;

function log(prev: State, line: string): State {
  const stage = prev.current ?? "plan";
  const next = [...prev.logs[stage], line];
  return {
    ...prev,
    phase: "running",
    logs: {
      ...prev.logs,
      [stage]:
        next.length > MAX_STAGE_LOG_LINES
          ? next.slice(-MAX_STAGE_LOG_LINES)
          : next,
    },
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
    const res = await fetch(
      `/api/experts/${encodeURIComponent(slug)}/build/status`,
    );
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
      return {
        ...prev,
        phase: "done",
        current: null,
        completed: [...BUILD_STAGES],
      };
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
        failedStage: prev.current,
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
