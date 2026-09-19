import { cn } from '@/lib/cn'

/**
 * Line drawings of the three things an expert comes with.
 *
 * Drawings, not screenshots, and deliberately so: a screenshot on a marketing
 * page is a claim about content — *this* answer, *these* numbers — and the only
 * content this site is willing to show is the recorded build log in the hero. A
 * wireframe claims only a shape: answers carry citation chips, the ledger has a
 * kept and a dropped column, the map is rings. All three shapes are the app's.
 *
 * Inline SVG in `currentColor`, so they follow the theme, cost no request and
 * need nothing from the CSP. Decorative: the card's own text says what each is.
 */

const frame = 'h-auto w-full'
const hair = { fill: 'none', stroke: 'currentColor', strokeWidth: 1 } as const

/** An answer: lines of prose, numbered chips, and the passage one points at. */
export function CitationWireframe({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 320 190" aria-hidden="true" className={cn(frame, className)}>
      <g className="text-fg-4" {...hair}>
        <rect x="0.5" y="0.5" width="319" height="189" rx="14" />
        <line x1="20" y1="30" x2="196" y2="30" />
        <line x1="20" y1="46" x2="150" y2="46" />
        <line x1="20" y1="78" x2="210" y2="78" />
        <line x1="20" y1="94" x2="120" y2="94" />
        {/* The chip's lead to its passage. */}
        <path d="M171 46 C 200 46, 200 128, 176 128" strokeDasharray="2 3" />
      </g>
      <g className="text-fg-2" {...hair}>
        <rect x="157" y="39" width="14" height="14" rx="7" />
        <rect x="127" y="87" width="14" height="14" rx="7" />
      </g>
      <g className="text-fg-3" {...hair}>
        <rect x="20" y="114" width="156" height="56" rx="10" />
        <line x1="32" y1="130" x2="150" y2="130" />
        <line x1="32" y1="142" x2="164" y2="142" />
        <line x1="32" y1="154" x2="112" y2="154" />
      </g>
      <g className="fill-current font-mono text-[8px] text-fg-2">
        <text x="164" y="49" textAnchor="middle">
          1
        </text>
        <text x="134" y="97" textAnchor="middle">
          2
        </text>
      </g>
    </svg>
  )
}

/** The ledger: a window of rows, each kept or dropped, each with its scores. */
export function LedgerWireframe({ className }: { className?: string }) {
  const rows = [
    { y: 58, kept: true, title: 150, score: 46 },
    { y: 82, kept: true, title: 118, score: 38 },
    { y: 106, kept: false, title: 134, score: 14 },
    { y: 130, kept: true, title: 96, score: 42 },
    { y: 154, kept: false, title: 126, score: 10 },
  ]
  return (
    <svg viewBox="0 0 320 190" aria-hidden="true" className={cn(frame, className)}>
      <g className="text-fg-4" {...hair}>
        <rect x="0.5" y="0.5" width="319" height="189" rx="14" />
        <line x1="0" y1="34" x2="320" y2="34" />
        <circle cx="18" cy="17" r="3" />
        <circle cx="30" cy="17" r="3" />
        <circle cx="42" cy="17" r="3" />
        {rows.map((row) => (
          <line key={row.y} x1="16" y1={row.y + 12} x2="304" y2={row.y + 12} />
        ))}
      </g>
      {rows.map((row) => (
        <g key={row.y} className={row.kept ? 'text-fg-2' : 'text-fg-4'} {...hair}>
          {row.kept ? (
            <path d={`M18 ${row.y} l3 3 l6 -7`} />
          ) : (
            <path d={`M18 ${row.y - 4} l8 8 M26 ${row.y - 4} l-8 8`} />
          )}
          <line x1="40" y1={row.y} x2={40 + row.title} y2={row.y} />
          {/* The score, as the length of a bar against its track. */}
          <line x1="250" y1={row.y} x2={250 + row.score} y2={row.y} strokeWidth="3" />
        </g>
      ))}
    </svg>
  )
}

/** The map: the subject at the centre, key concepts on a ring, sources beyond. */
export function MapWireframe({ className }: { className?: string }) {
  const concepts = [
    [160, 47],
    [226, 78],
    [212, 136],
    [108, 136],
    [94, 78],
  ]
  const sources = [
    [60, 40],
    [272, 52],
    [290, 120],
    [236, 172],
    [84, 172],
    [30, 116],
  ]
  return (
    <svg viewBox="0 0 320 190" aria-hidden="true" className={cn(frame, className)}>
      <g className="text-fg-4" {...hair}>
        <rect x="0.5" y="0.5" width="319" height="189" rx="14" />
        <ellipse cx="160" cy="95" rx="70" ry="48" />
        <ellipse cx="160" cy="95" rx="136" ry="82" strokeDasharray="2 4" />
        {concepts.map(([x, y]) => (
          <line key={`${x}-${y}`} x1="160" y1="95" x2={x} y2={y} />
        ))}
      </g>
      <g className="text-fg-3" {...hair}>
        {sources.map(([x, y]) => (
          <rect key={`${x}-${y}`} x={x - 4} y={y - 4} width="8" height="8" rx="2" />
        ))}
      </g>
      <g className="fill-current text-fg-2">
        {concepts.map(([x, y]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r="4" />
        ))}
      </g>
      <g className="text-fg-2" {...hair}>
        <rect x="148" y="83" width="24" height="24" rx="9" className="fill-panel" />
      </g>
    </svg>
  )
}
