/**
 * "Firefox on macOS" from a User-Agent string, for the session list.
 *
 * Deliberately small: the session list needs a name a person recognises, not
 * a version number, and a full parser is a dependency for one line of text.
 * Order matters — Edge and Opera also say "Chrome", and Chrome also says
 * "Safari".
 */

export interface DeviceLabel {
  label: string
  kind: 'desktop' | 'phone' | 'terminal' | 'unknown'
}

const BROWSERS: Array<[RegExp, string]> = [
  [/Edg(e|A|iOS)?\//, 'Edge'],
  [/OPR\/|Opera/, 'Opera'],
  [/Firefox\/|FxiOS\//, 'Firefox'],
  [/SamsungBrowser\//, 'Samsung Internet'],
  [/CriOS\/|Chrome\//, 'Chrome'],
  [/Safari\//, 'Safari'],
]

const SYSTEMS: Array<[RegExp, string]> = [
  [/iPhone/, 'iPhone'],
  [/iPad/, 'iPad'],
  [/Android/, 'Android'],
  [/CrOS/, 'ChromeOS'],
  [/Mac OS X|Macintosh/, 'macOS'],
  [/Windows/, 'Windows'],
  [/Linux/, 'Linux'],
]

export function describeUserAgent(agent: string | null | undefined): DeviceLabel {
  if (!agent) return { label: 'Unknown device', kind: 'unknown' }
  // The Rust TUI (reqwest) and the Python CLI (httpx) — and, before device
  // names were recorded, every session, because they all came from the API.
  if (/^python-httpx|^reqwest|^peritus/i.test(agent)) {
    return { label: 'Terminal app, or an older sign-in', kind: 'terminal' }
  }
  const browser = BROWSERS.find(([pattern]) => pattern.test(agent))?.[1]
  const system = SYSTEMS.find(([pattern]) => pattern.test(agent))?.[1]
  const phone = /iPhone|Android.*Mobile|Mobile Safari/.test(agent)
  if (!browser && !system) return { label: 'Unknown device', kind: 'unknown' }
  return {
    label: browser && system ? `${browser} on ${system}` : (browser ?? system ?? 'Unknown device'),
    kind: phone ? 'phone' : 'desktop',
  }
}
