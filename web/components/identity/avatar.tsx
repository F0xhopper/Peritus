import { cn } from '@/lib/cn'
import {
  pictureUrl,
  renderAvatarSvg,
  resolveRecipe,
  type AvatarRecipe,
  type AvatarSubject,
} from '@/lib/avatar'
import { expertIdentity } from '@/lib/persona'

/**
 * An expert's avatar: the found picture of its subject, the generated drawing
 * its owner chose, or the monogram sigil derived from its persona name.
 *
 * One component for all three, because every surface that shows an expert — the
 * rail, the sidebar header, a card, the breadcrumb, a chat message, a palette
 * row — wants "whatever this expert looks like" and must not know or care which
 * kind it is.
 *
 * The generated SVG is inlined rather than loaded as an image: it is under 2 KB,
 * it must appear in the server-rendered HTML (an avatar that pops in after
 * hydration is a layout shift on every row of a list), and an `<img src=data:>`
 * would cost a paint and cannot inherit the theme.
 *
 * The found picture *is* an `<img>`, because it is real bytes — served
 * same-origin from our own API under a content-hashed URL, so there is no
 * third-party origin in the browser and the cache can be immutable. It keeps
 * the rounded square: a circular crop reads as a headshot of the persona, and
 * the picture is explicitly a picture of the *subject*. It is also kept at 16px
 * and 20px rather than degrading to a monogram — a recognisable thumbnail beats
 * two letters at any size, and the bytes are already cached.
 */

export interface AvatarProps {
  expert: AvatarSubject
  size?: number
  /** `square` is the rail and list form; `circle` is the account avatar. */
  shape?: 'square' | 'circle'
  className?: string
  /** Overrides the stored recipe — the picker previews with this. */
  recipe?: AvatarRecipe
  /** Load the picture eagerly — for the rail, which is always on screen and
   *  otherwise flashed blank on each route change. */
  eager?: boolean
  /** Where the picture's bytes are, when not behind the signed-in slug route —
   *  the share page has a token and no slug. */
  pictureSrc?: string
}

export function Avatar({
  expert,
  size = 32,
  shape = 'square',
  className,
  recipe,
  eager,
  pictureSrc,
}: AvatarProps) {
  const resolved = recipe ?? resolveRecipe(expert)
  const radius = shape === 'circle' ? '9999px' : `${Math.max(4, Math.round(size * 0.3))}px`
  const svg = renderAvatarSvg(resolved, size)
  // Only reachable when `resolveRecipe` saw a picture, or when a preview recipe
  // asked for one on an expert that has it — both imply both fields are here.
  const picture =
    resolved.style === 'picture' && expert.picture?.version
      ? (pictureSrc ?? (expert.name ? pictureUrl(expert.name, expert.picture.version) : null))
      : null

  return (
    <span
      aria-hidden="true"
      data-avatar={resolved.style}
      style={{ width: size, height: size, borderRadius: radius }}
      className={cn(
        'relative inline-grid shrink-0 place-items-center overflow-hidden',
        // The tile under `rings` and `identicon`, which draw on transparency,
        // and the whole of the monogram's surface.
        'bg-expert-soft ring-1 ring-expert/40 ring-inset',
        className,
      )}
    >
      {picture ? (
        // `next/image` buys nothing here and costs a hop. The bytes are already
        // exactly the size we asked Wikimedia's thumbnail service for, they are
        // served same-origin under a content-hashed URL with a year's immutable
        // cache, and every render is a 16–64px square — so there is no layout
        // to reserve, no srcset worth generating and nothing left to optimise.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={picture}
          // Empty on purpose: the root span is `aria-hidden`, and the expert's
          // name is always adjacent to it on every surface that renders one.
          alt=""
          width={size}
          height={size}
          loading={eager ? 'eager' : 'lazy'}
          decoding="async"
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : svg ? (
        <span
          className="absolute inset-0 [&>svg]:h-full [&>svg]:w-full"
          // Generated locally from a bounded recipe by a pure function; no
          // user-supplied markup can reach this.
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : (
        <Monogram expert={expert} size={size} />
      )}
    </span>
  )
}

/** The default look: initials in `--expert` over two faint deterministic marks. */
function Monogram({ expert, size }: { expert: AvatarSubject; size: number }) {
  const { initials, seed } = expertIdentity(expert)
  const marks = MARKS[seed]
  // Below 24px the marks only muddy two letters that are already small.
  const showMarks = size >= 24

  return (
    <>
      {showMarks && (
        <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full" aria-hidden="true">
          {marks.map((m, i) => (
            <circle key={i} cx={m.cx} cy={m.cy} r={m.r} fill="var(--expert)" opacity={0.2} />
          ))}
        </svg>
      )}
      <span
        className="relative leading-none font-medium text-expert"
        style={{ fontSize: Math.max(8, Math.round(size * 0.4)), letterSpacing: '0.01em' }}
      >
        {initials}
      </span>
    </>
  )
}

/** Six mark layouts, chosen by the name hash. Coordinates are in a 0–100 box. */
const MARKS: { cx: number; cy: number; r: number }[][] = [
  [
    { cx: 24, cy: 30, r: 30 },
    { cx: 76, cy: 72, r: 22 },
  ],
  [
    { cx: 70, cy: 26, r: 26 },
    { cx: 30, cy: 76, r: 30 },
    { cx: 84, cy: 82, r: 14 },
  ],
  [
    { cx: 50, cy: 18, r: 24 },
    { cx: 18, cy: 66, r: 20 },
  ],
  [
    { cx: 82, cy: 50, r: 28 },
    { cx: 22, cy: 22, r: 18 },
  ],
  [
    { cx: 32, cy: 52, r: 34 },
    { cx: 80, cy: 20, r: 16 },
  ],
  [
    { cx: 62, cy: 62, r: 32 },
    { cx: 26, cy: 24, r: 20 },
  ],
]
