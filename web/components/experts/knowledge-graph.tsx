"use client";

import * as React from "react";
import {
  CrosshairIcon,
  MaximizeIcon,
  MinimizeIcon,
  MinusIcon,
  PlusIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { GraphEdge, GraphNode } from "@/lib/api/types";

// An explorer, not a picture.
//
// force-graph touches `window` at module-evaluation time, which breaks even
// inside a "use client" component: Next still evaluates the module during the
// server render pass for that component's tree. A dynamic import deferred into
// the effect keeps it out of that pass entirely.
//
// Laid out as a ball, not a force-directed scatter. Every node is pinned into a
// filled disc and the simulation never ticks, which buys three things springs
// can't: the same expert draws the same picture on every visit (a layout that
// shifts run to run can't be pointed at in a bug report), there is no settling
// period to sit through, and nothing wanders off-screen. The cost is that
// clusters no longer separate themselves spatially, so the *order* nodes are
// packed in has to do that work instead — see `adjacencyOrder`.
//
// The roundness is only half of it. A disc of evenly-sized dots is a disc; what
// makes it read as a sphere is the depth gradient — each node carries the height
// of a unit sphere over its position, and both size and opacity fall off with it,
// so the middle is large and bright and the limb is small and faint. Nothing
// here is projected from real 3D: it is a 2D layout wearing a lighting model.
//
// The API ranks nodes by *global* degree and then returns only the edges falling
// between the ones it kept, so on a real corpus several hundred arrive with
// every partner cut away by the cap. That is a truncated view, not bad data — so
// the default is the part of the graph that still has its relationships, packed
// into the ball, with the orphans as a dim skin outside it, one toggle away and
// counted rather than silently dropped.
//
// Everything is encoded in shape, weight and opacity, never hue: the theme is
// achromatic on purpose (see globals.css), and a graph is exactly the surface
// that tempts you to break that.
//
//   concept      filled disc          claim        hollow ring
//   edge weight  line width           contradicts  dashed line
//
// Hover and search live in a ref rather than React state: force-graph repaints
// on its own animation loop, and re-rendering the tree on every mousemove over
// the canvas fights it. Selection is the exception — it drives the inspector
// panel, which is React — so it is mirrored into both.

const NODE_LABEL_LIMIT = 28;

/** How many of the best-connected nodes keep a permanent label. Enough to
 * orient by at first paint; past this the labels overlap into a grey mat. */
const ALWAYS_LABELLED = 12;

/** Distance between neighbouring nodes inside the ball, in graph units. Sets
 * both the spacing along a band and the gap between bands. `nodeRadius` tops out
 * around 22 units across for the heaviest hub, so this clears the worst case of
 * two hubs landing side by side with a little daylight left over. */
const BALL_SPACING = 24;

/** Turn applied between consecutive bands. The golden angle is the one value
 * that never repeats into radial alignment, which is what stops a concentric
 * layout from looking like a dartboard. */
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/** Empty bands between the connected ball and the orphan skin outside it, so
 * the two read as separate things rather than one larger ball. */
const ORPHAN_MOAT_BANDS = 1;

/** Depth assigned to orphans. They sit outside the ball, so they get a shallow
 * fixed value — dim enough to read as a haze around it, bright enough to still
 * be visible when the toggle brings them in. */
const ORPHAN_DEPTH = 0.3;

interface SimNode {
  id: number;
  label: string;
  nodeType: string | null;
  /** Degree within the returned subgraph — what is actually drawn — as opposed
   * to the API's `degree`, which also counts edges to nodes beyond the cap. */
  degree: number;
  x?: number;
  y?: number;
  /** Pinned position. force-graph hands these straight to d3-force, which treats
   * them as fixed, so the drawn layout is the one computed here. */
  fx?: number;
  fy?: number;
  /** Bearing from the centre of the ball, in radians. Labels read outward along
   * it, away from the crowded middle. */
  angle?: number;
  /** Height of the sphere over this point: 1 at the centre, 0 at the limb.
   * Drives node size and opacity, and is the whole reason a flat disc of dots
   * reads as a curved surface. */
  depth?: number;
}

interface SimLink {
  source: number | SimNode;
  target: number | SimNode;
  edgeType: string;
  weight: number;
}

/** One end of a relationship, for the inspector's neighbour list. */
interface Neighbour {
  id: number;
  label: string;
  edgeType: string;
  /** True when the selected node is the edge's source. */
  outgoing: boolean;
}

type Graph = InstanceType<typeof import("force-graph").default<SimNode, SimLink>>;

export function KnowledgeGraph({
  nodes,
  edges,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
}) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const graphRef = React.useRef<Graph | null>(null);

  const [query, setQuery] = React.useState("");
  const [showOrphans, setShowOrphans] = React.useState(false);
  const [selected, setSelected] = React.useState<SimNode | null>(null);
  const [fullscreen, setFullscreen] = React.useState(false);

  // Derived once per dataset: adjacency, in-view degree, and the split between
  // nodes that still have relationships here and ones whose partners the node
  // cap cut away.
  const model = React.useMemo(() => buildModel(nodes, edges), [nodes, edges]);

  // Read by the canvas accessors on every frame. Refs, so typing in the search
  // box or moving the pointer never re-renders the React tree.
  const view = React.useRef({
    hovered: null as SimNode | null,
    selectedId: null as number | null,
    matches: null as Set<number> | null,
    showOrphans: false,
  });

  const visible = React.useCallback(
    (n: SimNode) => n.degree > 0 || view.current.showOrphans,
    [],
  );

  // ── the canvas ─────────────────────────────────────────────────────────
  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    let graph: Graph | null = null;
    let observer: ResizeObserver | null = null;
    let cancelled = false;

    void import("force-graph").then(({ default: ForceGraph }) => {
      if (cancelled) return;

      const style = getComputedStyle(document.documentElement);
      const foreground =
        style.getPropertyValue("--foreground").trim() || "#ededed";
      const muted =
        style.getPropertyValue("--muted-foreground").trim() || "#9b9b9b";

      const isVisible = (n: SimNode) => n.degree > 0 || view.current.showOrphans;

      /** Whether a node is at full strength: nothing is focused, or it is the
       * focus, or it neighbours it, or it answers the current search.
       *
       * A focus outranks the search deliberately. Searching narrows the field
       * to a handful of candidates; picking one of them is the next step, and
       * if the search kept dimming everything the chosen node would sit alone
       * in a grey field with its relationships — the reason you went looking —
       * greyed out with everything else. */
      const focusId = () => view.current.hovered?.id ?? view.current.selectedId;

      const nodeIsLit = (n: SimNode) => {
        const focus = focusId();
        if (focus !== null && focus !== undefined) {
          return n.id === focus || !!model.neighbourIds.get(focus)?.has(n.id);
        }
        const { matches } = view.current;
        return matches ? matches.has(n.id) : true;
      };

      const linkIsLit = (l: SimLink) => {
        const s = endpointId(l.source);
        const t = endpointId(l.target);
        const focus = focusId();
        if (focus !== null && focus !== undefined) {
          return s === focus || t === focus;
        }
        const { matches } = view.current;
        return matches ? matches.has(s) && matches.has(t) : true;
      };

      const focused = () =>
        view.current.hovered !== null ||
        view.current.selectedId !== null ||
        view.current.matches !== null;

      graph = new ForceGraph<SimNode, SimLink>(el)
        .graphData({ nodes: model.simNodes, links: model.simLinks })
        .backgroundColor("rgba(0,0,0,0)")
        .width(el.clientWidth)
        .height(el.clientHeight)
        // Every accessor below reads live from `view`, which changes on hover
        // and on search without React or force-graph being told. Left paused,
        // the canvas would simply not repaint for any of it. The obvious fix —
        // re-setting a prop to mark the component dirty — is worse than it
        // looks: a prop set runs the whole update cycle and resets the
        // simulation's cooldown counter, so moving the pointer across the
        // canvas kept the layout permanently reheating and it never settled.
        .autoPauseRedraw(false)
        .nodeRelSize(3)
        .nodeVal((n) => 1 + Math.sqrt(n.degree))
        .nodeVisibility(isVisible)
        .linkVisibility(
          (l) => isVisible(asNode(l.source)) && isVisible(asNode(l.target)),
        )
        // Straight. Curvature earned its keep when every edge was a chord across
        // a hollow ring; inside a filled ball the placement order already keeps
        // edges short, and bowing them only adds noise over the dense middle.
        .linkCurvature(0)
        // Weight is the only thing an edge has to say beyond "these two are
        // related", so it gets the one channel a hairline drawing has spare.
        .linkWidth((l) => (linkIsLit(l) ? 0.4 + l.weight * 1.6 : 0.4))
        .linkColor((l) => {
          // Edges fade with the depth of the shallower end, so relationships
          // near the limb recede with the nodes they join.
          const fade =
            0.6 +
            0.4 *
              Math.max(
                asNode(l.source).depth ?? 1,
                asNode(l.target).depth ?? 1,
              );
          if (!linkIsLit(l)) return `rgba(155,155,155,${0.06 * fade})`;
          return focused()
            ? `rgba(237,237,237,${0.65 * fade})`
            : `rgba(155,155,155,${0.3 * fade})`;
        })
        // Disagreement is the one relationship a reader scanning this actually
        // hunts for, and it cannot be a colour here — so it is the only broken
        // line on the canvas.
        .linkLineDash((l) => (l.edgeType === "contradicts" ? [3, 3] : null))
        .nodeLabel(() => "")
        .nodeCanvasObject((node, ctx, scale) => {
          const r = nodeRadius(node);
          const lit = nodeIsLit(node);
          const isSelected = view.current.selectedId === node.id;

          // Depth dims the node along with its size — except when it is the one
          // being looked at, which must not be faint just for sitting near the
          // limb.
          const depth = focusId() === node.id ? 1 : depthAlpha(node);
          ctx.globalAlpha = (focused() ? (lit ? 1 : 0.18) : 0.92) * depth;

          ctx.beginPath();
          ctx.arc(node.x!, node.y!, r, 0, 2 * Math.PI, false);
          if (node.nodeType === "claim") {
            // A claim is an assertion the corpus makes, not a thing it names —
            // hollow, so the two read apart without a second hue.
            ctx.strokeStyle = lit ? foreground : muted;
            ctx.lineWidth = Math.max(0.6, r * 0.34);
            ctx.stroke();
          } else {
            ctx.fillStyle = lit ? foreground : muted;
            ctx.fill();
          }

          if (isSelected) {
            ctx.beginPath();
            ctx.arc(node.x!, node.y!, r + 2.5, 0, 2 * Math.PI, false);
            ctx.strokeStyle = foreground;
            ctx.lineWidth = 1;
            ctx.stroke();
          }

          // Hubs stay named so the graph is readable before you touch it;
          // everything else earns a label by being focused, by matching the
          // search, or by being zoomed far enough in to have room for one.
          const showLabel =
            isSelected ||
            view.current.hovered?.id === node.id ||
            (focused() ? lit : model.hubIds.has(node.id) || scale > 2.2);

          if (showLabel) {
            const size = Math.max(11 / scale, 2.5);
            const angle = node.angle ?? 0;
            const dx = Math.cos(angle);
            ctx.font = `${size}px var(--font-literata), serif`;
            // Labels run outward along the radius, away from the crowded middle
            // of the ball. Set below the node as they were, they would land on
            // top of the neighbours — one `BALL_SPACING` away in every direction.
            ctx.textAlign = dx >= 0 ? "left" : "right";
            ctx.textBaseline = "middle";
            ctx.fillStyle = foreground;
            ctx.globalAlpha = lit ? 1 : 0.3;
            ctx.fillText(
              truncate(node.label),
              node.x! + dx * (r + 3),
              node.y! + Math.sin(angle) * (r + 3),
            );
          }
          ctx.globalAlpha = 1;
        })
        .nodePointerAreaPaint((node, color, ctx) => {
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, nodeRadius(node) + 2, 0, 2 * Math.PI, false);
          ctx.fill();
        })
        .onNodeHover((node) => {
          view.current.hovered = node;
          el.style.cursor = node ? "pointer" : "default";
        })
        .onNodeClick((node) => {
          view.current.selectedId = node.id;
          setSelected(node);
          graph?.centerAt(node.x, node.y, 400);
          graph?.zoom(Math.max(graph.zoom(), 2.4), 400);
        })
        .onBackgroundClick(() => {
          view.current.selectedId = null;
          setSelected(null);
        })
        // Wheel zoom only with a modifier held. Unmodified, the wheel belongs
        // to the page: this canvas is 34rem tall inside a page that scrolls,
        // and grabbing the wheel meant scrolling past the graph zoomed it
        // instead — leaving the reader stranded at 8× with no obvious way back.
        // macOS trackpad pinch arrives as a ctrl-wheel event, so pinch-to-zoom
        // still works, and the toolbar carries explicit +/−/fit either way.
        .enableZoomInteraction((e) => e.ctrlKey || e.metaKey)
        // Every node is pinned, so there is nothing to simulate. A cooldown of
        // zero stops the engine on the very first frame — before `tick()` is
        // called even once — and `onEngineStop` fires there to frame the ball.
        // The d3 charge and link forces are left at their defaults deliberately:
        // they never run, so tuning them would be describing a layout that
        // isn't happening.
        .cooldownTicks(0)
        // Dragging would tear a node out of the packing for the rest of the
        // session, and break the depth gradient's agreement with position.
        .enableNodeDrag(false)
        .onEngineStop(() => {
          graph?.zoomToFit(500, 48, isVisible);
        });

      graphRef.current = graph;

      observer = new ResizeObserver(() => {
        graph?.width(el.clientWidth).height(el.clientHeight);
      });
      observer.observe(el);
    });

    return () => {
      cancelled = true;
      observer?.disconnect();
      graph?._destructor();
      graphRef.current = null;
      el.replaceChildren();
    };
  }, [model]);

  // ── search ─────────────────────────────────────────────────────────────
  const matches = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    return model.simNodes.filter((n) => n.label.toLowerCase().includes(q));
  }, [query, model.simNodes]);

  React.useEffect(() => {
    view.current.matches = matches ? new Set(matches.map((n) => n.id)) : null;
  }, [matches]);

  React.useEffect(() => {
    view.current.showOrphans = showOrphans;
    graphRef.current?.zoomToFit(400, 48, visible);
  }, [showOrphans, visible]);

  const focusNode = React.useCallback(
    (id: number) => {
      const node = model.byId.get(id);
      if (!node) return;
      view.current.selectedId = id;
      setSelected(node);
      const g = graphRef.current;
      g?.centerAt(node.x, node.y, 400);
      g?.zoom(Math.max(g.zoom(), 2.4), 400);
    },
    [model.byId],
  );

  const clearSelection = React.useCallback(() => {
    view.current.selectedId = null;
    setSelected(null);
  }, []);

  // Escape backs out one level at a time — selection first, then fullscreen —
  // which is the order they were entered in.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (view.current.selectedId !== null) clearSelection();
      else if (fullscreen) setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clearSelection, fullscreen]);

  const zoomBy = (factor: number) => {
    const g = graphRef.current;
    if (g) g.zoom(g.zoom() * factor, 250);
  };

  return (
    <div className={cn("flex flex-col", fullscreen && "fixed inset-0 z-50 bg-background")}>
      <Toolbar
        query={query}
        onQueryChange={setQuery}
        matchCount={matches?.length ?? null}
        onFirstMatch={() => matches?.[0] && focusNode(matches[0].id)}
        orphanCount={model.orphanCount}
        showOrphans={showOrphans}
        onToggleOrphans={() => setShowOrphans((v) => !v)}
        fullscreen={fullscreen}
        onToggleFullscreen={() => setFullscreen((v) => !v)}
        onZoomIn={() => zoomBy(1.4)}
        onZoomOut={() => zoomBy(1 / 1.4)}
        onFit={() => graphRef.current?.zoomToFit(400, 48, visible)}
      />

      <div className="relative min-h-0 flex-1">
        <div
          ref={containerRef}
          className={cn("w-full", fullscreen ? "h-full" : "h-[34rem]")}
        />

        <Legend />

        {selected && (
          <Inspector
            node={selected}
            neighbours={model.neighbours.get(selected.id) ?? []}
            onClose={clearSelection}
            onFocus={focusNode}
          />
        )}
      </div>
    </div>
  );
}

function Toolbar({
  query,
  onQueryChange,
  matchCount,
  onFirstMatch,
  orphanCount,
  showOrphans,
  onToggleOrphans,
  fullscreen,
  onToggleFullscreen,
  onZoomIn,
  onZoomOut,
  onFit,
}: {
  query: string;
  onQueryChange: (v: string) => void;
  matchCount: number | null;
  onFirstMatch: () => void;
  orphanCount: number;
  showOrphans: boolean;
  onToggleOrphans: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border/60 p-3">
      <div className="relative min-w-48 flex-1">
        <SearchIcon
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onFirstMatch();
            }
          }}
          placeholder="Find a concept…"
          aria-label="Find a concept"
          className="h-8 pl-8 text-sm"
        />
      </div>

      {matchCount !== null && (
        <span className="text-xs text-muted-foreground tabular-nums">
          {matchCount === 0
            ? "No match"
            : `${matchCount} match${matchCount === 1 ? "" : "es"}`}
        </span>
      )}

      {orphanCount > 0 && (
        <Button
          variant="ghost"
          size="xs"
          onClick={onToggleOrphans}
          // Says what is being withheld and how many, rather than quietly
          // dropping a third of the nodes the header just counted.
          title="These concepts have no relationship to anything else inside this view"
        >
          {showOrphans ? "Hide" : "Show"} {orphanCount} unconnected
        </Button>
      )}

      <div className="ml-auto flex items-center gap-1">
        <Button variant="ghost" size="icon-sm" aria-label="Zoom out" onClick={onZoomOut}>
          <MinusIcon />
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Zoom in" onClick={onZoomIn}>
          <PlusIcon />
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Fit to view" onClick={onFit}>
          <CrosshairIcon />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={fullscreen ? "Exit fullscreen" : "Fullscreen"}
          onClick={onToggleFullscreen}
        >
          {fullscreen ? <MinimizeIcon /> : <MaximizeIcon />}
        </Button>
      </div>
    </div>
  );
}

/** What the shapes mean. Without it, concept vs claim is a difference the
 * reader can see but not name. */
function Legend() {
  return (
    <ul className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-1.5 text-[0.6875rem] text-muted-foreground">
      <li className="flex items-center gap-2">
        <span aria-hidden className="size-2 rounded-full bg-foreground" />
        Concept
      </li>
      <li className="flex items-center gap-2">
        <span aria-hidden className="size-2 rounded-full border border-foreground" />
        Claim
      </li>
      <li className="flex items-center gap-2">
        <span aria-hidden className="h-px w-4 bg-muted-foreground" />
        Related
      </li>
      <li className="flex items-center gap-2">
        <span
          aria-hidden
          className="w-4 border-t border-dashed border-muted-foreground"
        />
        Contradicts
      </li>
    </ul>
  );
}

/** The panel that makes a node worth clicking: what it is, how connected it is,
 * and every relationship it has — each one a way further in. */
function Inspector({
  node,
  neighbours,
  onClose,
  onFocus,
}: {
  node: SimNode;
  neighbours: Neighbour[];
  onClose: () => void;
  onFocus: (id: number) => void;
}) {
  return (
    <aside className="absolute top-3 right-3 flex max-h-[calc(100%-1.5rem)] w-64 flex-col rounded-lg border border-border bg-card/95 shadow-lg backdrop-blur-sm">
      <div className="flex items-start gap-2 border-b border-border/60 p-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-snug font-medium">{node.label}</p>
          <p className="text-eyebrow mt-1 text-muted-foreground">
            {node.nodeType === "claim" ? "Claim" : "Concept"} ·{" "}
            {neighbours.length} {neighbours.length === 1 ? "link" : "links"}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Close details"
          onClick={onClose}
        >
          <XIcon />
        </Button>
      </div>

      {neighbours.length === 0 ? (
        <p className="p-3 text-xs text-muted-foreground">
          No relationships inside this view.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {neighbours.map((n, i) => (
            <li key={`${n.id}-${n.edgeType}-${n.outgoing}-${i}`}>
              <button
                type="button"
                onClick={() => onFocus(n.id)}
                className="flex w-full flex-col gap-0.5 rounded-md px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="text-eyebrow text-muted-foreground">
                  {relationLabel(n.edgeType, n.outgoing)}
                </span>
                <span className="text-xs leading-snug">{n.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

// ── model ────────────────────────────────────────────────────────────────

function buildModel(nodes: GraphNode[], edges: GraphEdge[]) {
  const byId = new Map<number, SimNode>();
  const simNodes: SimNode[] = nodes.map((n) => {
    const sim: SimNode = {
      id: n.id,
      label: n.label,
      nodeType: n.node_type,
      degree: 0, // filled in below, from the edges actually present
    };
    byId.set(n.id, sim);
    return sim;
  });

  const neighbourIds = new Map<number, Set<number>>();
  const neighbours = new Map<number, Neighbour[]>();
  const simLinks: SimLink[] = [];

  for (const e of edges) {
    const from = byId.get(e.source);
    const to = byId.get(e.target);
    // The API only returns edges between returned nodes, but a dangling one
    // would silently corrupt every degree below it, so it is checked.
    if (!from || !to || from === to) continue;

    from.degree += 1;
    to.degree += 1;
    simLinks.push({
      source: e.source,
      target: e.target,
      edgeType: e.edge_type,
      // Absent weights are common in older extractions; treated as full
      // strength rather than as a hairline that would read as a weak claim.
      weight: e.weight ?? 1,
    });

    push(neighbourIds, e.source, e.target);
    push(neighbourIds, e.target, e.source);
    pushNeighbour(neighbours, e.source, {
      id: e.target,
      label: to.label,
      edgeType: e.edge_type,
      outgoing: true,
    });
    pushNeighbour(neighbours, e.target, {
      id: e.source,
      label: from.label,
      edgeType: e.edge_type,
      outgoing: false,
    });
  }

  const hubIds = new Set(
    [...simNodes]
      .sort((a, b) => b.degree - a.degree)
      .slice(0, ALWAYS_LABELLED)
      .filter((n) => n.degree > 0)
      .map((n) => n.id),
  );

  // Positions are a property of the dataset, so they are computed here with the
  // rest of the model and never recomputed on a repaint.
  layoutBall(simNodes, byId, neighbourIds);

  return {
    simNodes,
    simLinks,
    byId,
    neighbourIds,
    neighbours,
    hubIds,
    orphanCount: simNodes.filter((n) => n.degree === 0).length,
  };
}

// ── ball layout ──────────────────────────────────────────────────────────

/** Pack every node into a filled disc, then give each one a depth so the flat
 * canvas reads as a sphere.
 *
 * Filling outward from the centre in concentric bands, in adjacency order, does
 * two jobs at once. The best-connected node lands at the middle with its
 * neighbours in the first bands around it, so hubs sit where the eye goes first
 * and most edges stay short. And because the bands fill in order, hiding the
 * orphans on the outside leaves the inner ball byte-for-byte identical — a
 * reader who flips the toggle to see what was withheld doesn't get the graph
 * they were reading rearranged underneath them. */
function layoutBall(
  simNodes: SimNode[],
  byId: Map<number, SimNode>,
  neighbourIds: Map<number, Set<number>>,
) {
  const connected = adjacencyOrder(
    simNodes.filter((n) => n.degree > 0),
    byId,
    neighbourIds,
  );
  // Orphans have no relationships left to honour, so alphabetical — it is the
  // one order that makes the outer haze scannable by eye.
  const orphans = simNodes
    .filter((n) => n.degree === 0)
    .sort((a, b) => a.label.localeCompare(b.label));

  const radius = fillBall(connected, 0);
  fillBall(orphans, bandCount(connected.length) + ORPHAN_MOAT_BANDS);

  // Height of a unit sphere over the point, which is what turns the flat disc
  // into a ball: full at the centre, falling to nothing at the limb. Normalised
  // against the *connected* radius so the gradient is the same whether or not
  // the orphan skin is showing.
  for (const node of connected) {
    const r = Math.min(1, Math.hypot(node.x!, node.y!) / Math.max(radius, 1));
    node.depth = Math.sqrt(Math.max(0, 1 - r * r));
  }
  for (const node of orphans) node.depth = ORPHAN_DEPTH;
}

/** How many nodes band `k` holds: as many as fit one `BALL_SPACING` apart around
 * a circle of radius `k * BALL_SPACING`. Capacity grows linearly with `k`, which
 * is what keeps areal density even from the centre out. */
function bandCapacity(k: number): number {
  return k === 0 ? 1 : Math.max(1, Math.floor(2 * Math.PI * k));
}

/** Bands needed to hold `count` nodes. */
function bandCount(count: number): number {
  let bands = 0;
  let placed = 0;
  while (placed < count) {
    placed += bandCapacity(bands);
    bands++;
  }
  return bands;
}

/** Place `ordered` into concentric bands from `firstBand` outward. Returns the
 * radius of the outermost band used. */
function fillBall(ordered: SimNode[], firstBand: number): number {
  let i = 0;
  let k = firstBand;
  let offset = 0;

  while (i < ordered.length) {
    const take = Math.min(bandCapacity(k), ordered.length - i);
    const radius = k * BALL_SPACING;
    // Spread whatever landed here evenly around the whole band rather than at
    // the band's natural spacing: a part-filled last band would otherwise leave
    // a missing wedge, which reads as data having failed to load.
    const step = (2 * Math.PI) / take;

    for (let j = 0; j < take; j++) {
      const node = ordered[i + j];
      const angle = offset + j * step;
      node.angle = angle;
      node.x = node.fx = Math.cos(angle) * radius;
      node.y = node.fy = Math.sin(angle) * radius;
    }

    i += take;
    offset += GOLDEN_ANGLE;
    k++;
  }
  return Math.max(0, k - 1) * BALL_SPACING;
}

/** Placement order, chosen so related nodes land next to each other.
 *
 * The order *is* the layout here, and it is the difference between a readable
 * graph and a ball of string: two neighbours placed on opposite sides draw an
 * edge straight across the whole diameter, and a few hundred of those is an
 * opaque mat. A breadth-first walk from the best-connected node, taking each
 * node's own neighbours in descending degree, keeps a cluster contiguous so its
 * edges stay short. Minimising crossings properly is NP-hard; this costs one
 * pass and buys most of the legibility.
 *
 * Restarting from the next-best unvisited seed after each component drains means
 * disconnected clusters occupy their own region of the ball rather than
 * interleaving. */
function adjacencyOrder(
  nodes: SimNode[],
  byId: Map<number, SimNode>,
  neighbourIds: Map<number, Set<number>>,
): SimNode[] {
  const pending = new Set(nodes.map((n) => n.id));
  const seeds = [...nodes].sort((a, b) => b.degree - a.degree);
  const ordered: SimNode[] = [];

  for (const seed of seeds) {
    if (!pending.has(seed.id)) continue;
    pending.delete(seed.id);
    const queue = [seed];
    while (queue.length) {
      const node = queue.shift()!;
      ordered.push(node);
      const next = [...(neighbourIds.get(node.id) ?? [])]
        .filter((id) => pending.has(id))
        .map((id) => byId.get(id))
        .filter((n): n is SimNode => n !== undefined)
        .sort((a, b) => b.degree - a.degree);
      for (const n of next) {
        pending.delete(n.id);
        queue.push(n);
      }
    }
  }
  return ordered;
}

function push(map: Map<number, Set<number>>, key: number, value: number) {
  const set = map.get(key);
  if (set) set.add(value);
  else map.set(key, new Set([value]));
}

function pushNeighbour(
  map: Map<number, Neighbour[]>,
  key: number,
  value: Neighbour,
) {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

/** force-graph swaps link endpoints from ids to node objects once the
 * simulation has initialised, so both shapes have to be handled. Before that
 * swap a visibility test has nothing to read, and treating the endpoint as
 * connected is the safe answer — it is about to be resolved anyway. */
function asNode(ref: number | SimNode): SimNode {
  return typeof ref === "object" ? ref : ({ degree: 1 } as SimNode);
}

function endpointId(ref: number | SimNode): number {
  return typeof ref === "object" ? ref.id : ref;
}

function nodeRadius(node: SimNode): number {
  // Degree sets the base size; depth shrinks it toward the limb. Without the
  // second term the ball is a flat disc of evenly-sized dots — the size and
  // opacity gradients together are what make it read as curved.
  return (2 + Math.sqrt(node.degree)) * 1.6 * (0.55 + 0.45 * (node.depth ?? 1));
}

/** Opacity multiplier for a node's depth, on the same gradient as its size. */
function depthAlpha(node: SimNode): number {
  return 0.45 + 0.55 * (node.depth ?? 1);
}

function truncate(label: string): string {
  return label.length > NODE_LABEL_LIMIT
    ? `${label.slice(0, NODE_LABEL_LIMIT - 1)}…`
    : label;
}

/** Reads the relationship from the selected node's side, so the list is a set
 * of sentences about it rather than a column of raw enum values. */
const FORWARD: Record<string, string> = {
  supports: "supports",
  contradicts: "contradicts",
  builds_on: "builds on",
  defines: "defines",
  exemplifies: "exemplifies",
  cites: "cites",
};

const BACKWARD: Record<string, string> = {
  supports: "supported by",
  contradicts: "contradicted by",
  builds_on: "built on by",
  defines: "defined by",
  exemplifies: "exemplified by",
  cites: "cited by",
};

function relationLabel(edgeType: string, outgoing: boolean): string {
  return (
    (outgoing ? FORWARD : BACKWARD)[edgeType] ?? edgeType.replace(/_/g, " ")
  );
}
