/**
 * Formatting helpers.
 *
 * The rule that matters here: **`null` means "not recorded", never zero.**
 * Every count the API does not persist comes back as null with a reason, and a
 * fabricated zero in an evidence record is worse than a visible gap
 * (audit-api.md). `notRecorded` is what that renders as, and no helper in this
 * file ever coerces null to 0.
 */

const NOT_RECORDED = '—'

/** The em dash every unrecorded value renders as. */
export function notRecorded(): string {
  return NOT_RECORDED
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_RECORDED
  return formatInt(value)
}

/**
 * An integer with thousands separators, written out rather than delegated.
 *
 * `toLocaleString` is `Intl`, and `Intl` is not stable across engines — the
 * same rule that keeps every rendered date out of it (see `formatDate`). A
 * grouped number is three lines of arithmetic; a hydration mismatch is not.
 */
export function formatInt(value: number): string {
  const negative = value < 0
  const digits = Math.abs(Math.trunc(value)).toString()
  let out = ''
  for (let i = 0; i < digits.length; i += 1) {
    if (i > 0 && (digits.length - i) % 3 === 0) out += ','
    out += digits[i]
  }
  return negative ? `-${out}` : out
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return NOT_RECORDED
  return `${(value * 100).toFixed(digits)}%`
}

/** Money, to the cent — or to four places when it is smaller than a cent. */
export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_RECORDED
  if (value !== 0 && Math.abs(value) < 0.01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}

export function formatCredits(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_RECORDED
  return `${value} ${Math.abs(value) === 1 ? 'credit' : 'credits'}`
}

const RELATIVE = new Intl.RelativeTimeFormat('en-GB', { numeric: 'auto', style: 'narrow' })

/**
 * Month names written out rather than asked of `Intl`.
 *
 * `toLocaleDateString('en-GB', { month: 'short' })` is **not stable across
 * engines**: Node and Chromium's ICU render September as "Sept", WebKit's as
 * "Sep". Every absolute date is rendered on the server and then hydrated on the
 * client, so a disagreement between the two is a hydration text mismatch
 * (React #418) — which does not merely warn: React throws away the server HTML
 * for that whole subtree and re-renders it, and in iOS Safari that was enough
 * to replace the expert page with "This page couldn't load".
 *
 * Three letters for every month also keeps a column of dates the same width,
 * which the ledger and the credit table both rely on.
 */
const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const

const pad = (value: number): string => String(value).padStart(2, '0')

/**
 * "3m", "yesterday", "2 Mar".
 *
 * Deliberately absolute past a week: "47 days ago" is harder to read than a
 * date, and a research corpus is something people come back to months later.
 */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return NOT_RECORDED
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return NOT_RECORDED

  const seconds = Math.round((then.getTime() - Date.now()) / 1000)
  const abs = Math.abs(seconds)

  if (abs < 45) return 'now'
  if (abs < 3600) return RELATIVE.format(Math.round(seconds / 60), 'minute')
  if (abs < 86_400) return RELATIVE.format(Math.round(seconds / 3600), 'hour')
  if (abs < 7 * 86_400) return RELATIVE.format(Math.round(seconds / 86_400), 'day')
  return formatDate(iso)
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return NOT_RECORDED
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return NOT_RECORDED
  const sameYear = date.getFullYear() === new Date().getFullYear()
  const day = `${date.getDate()} ${MONTHS[date.getMonth()]}`
  return sameYear ? day : `${day} ${date.getFullYear()}`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return NOT_RECORDED
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return NOT_RECORDED
  return `${formatDate(iso)}, ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** `hh:mm:ss` for a build log row. */
export function formatClock(iso: string | null | undefined): string {
  if (!iso) return '--:--:--'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** "4m 12s" — an elapsed duration, for a running build. */
export function formatElapsed(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return NOT_RECORDED
  const total = Math.floor(seconds)
  const days = Math.floor(total / 86_400)
  const hours = Math.floor((total % 86_400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  if (days) return `${days}d ${hours}h`
  if (hours) return `${hours}h ${minutes}m`
  if (minutes) return `${minutes}m ${secs}s`
  return `${secs}s`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Title case a snake_case or kebab-case machine value for display. */
export function humanise(value: string | null | undefined): string {
  if (!value) return NOT_RECORDED
  const spaced = value.replace(/[_-]+/g, ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** "1 source", "3 sources" — a count with its noun agreeing. */
export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`
}

/** A chat's title for display: sentence case, or "Untitled chat". Older titles
 *  were stored in whatever casing the question was typed. */
export function chatTitle(title: string | null | undefined): string {
  const trimmed = title?.trim()
  if (!trimmed) return 'Untitled chat'
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1)
}

/** A prose field's first sentence (the whole text when it has no full stop),
 *  capped at 220 characters. The voice line and the Home card's description. */
export function firstSentence(text: string | null | undefined): string | null {
  const trimmed = text?.trim()
  if (!trimmed) return null
  const match = /^.+?[.!?](?=\s|$)/.exec(trimmed)
  const sentence = match ? match[0] : trimmed
  return sentence.length > 220 ? `${sentence.slice(0, 217).trimEnd()}…` : sentence
}

/** Cut at a word boundary, with an ellipsis. */
export function truncate(value: string, max: number): string {
  if (value.length <= max) return value
  const cut = value.slice(0, max)
  const space = cut.lastIndexOf(' ')
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`
}

/** A URL's host, for the ledger's source column. */
export function hostOf(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return null
  }
}
