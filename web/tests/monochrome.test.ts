import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * The app is monochrome, and this is what keeps it so (web/AGENTS.md, "Colour").
 *
 * Hue survives on **marks** only — the 8px status dot, the ring and the corner
 * dot on a building or failed avatar, the dispute mark on a chip or the map,
 * the 4px segments of the stage timeline and the password meter. It never
 * colours text, a background, a border or a button: those say what they mean
 * in words, in a glyph, or in fill against hairline. A `text-warn` on a count
 * or a `bg-bad/12` on a notice is the regression this test exists to catch, so
 * the allowlist below is every file that may name a status token, with the
 * number of times it may. Adding to it is a design decision, not a fix.
 */

const ROOT = join(__dirname, '..')
const SCANNED = ['app', 'components', 'hooks', 'lib']

/** Files that may use a status token, and how many uses they hold. */
const MARKS: Record<string, number> = {
  'components/ui/status-dot.tsx': 5,
  'components/shell/rail.tsx': 2,
  'components/shell/nav-drawer.tsx': 1,
  'components/experts/building-now.tsx': 2,
  'components/knowledge/kind-icon.tsx': 2,
  'components/chat/citations.tsx': 1,
  'components/build/stage-timeline.tsx': 2,
  'components/auth/password-meter.tsx': 4,
  // The map's dispute mark reads `--warn` into the canvas palette.
  'lib/brain/paint.ts': 1,
}

const TOKEN =
  /\b(?:text|bg|border|ring|fill|stroke|decoration|outline|shadow|divide|placeholder|from|via|to)-(?:ok|warn|bad|info)(?:\/\d+)?\b|var\(--(?:ok|warn|bad|info)\)|read\('--(?:ok|warn|bad|info)'/g

function* files(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) yield* files(path)
    // Not `globals.css`: it is where the tokens are defined.
    else if (/\.tsx?$/.test(name) && !name.endsWith('.generated.ts')) yield path
  }
}

describe('monochrome', () => {
  it('names a status colour only on the marks that are allowed one', () => {
    const found: Record<string, number> = {}
    for (const dir of SCANNED) {
      for (const path of files(join(ROOT, dir))) {
        const uses = readFileSync(path, 'utf8').match(TOKEN)?.length ?? 0
        if (uses) found[relative(ROOT, path)] = uses
      }
    }
    expect(found).toEqual(MARKS)
  })

  it('keeps the three hues defined, for the marks', () => {
    const css = readFileSync(join(ROOT, 'app/globals.css'), 'utf8')
    for (const token of ['--ok', '--warn', '--bad']) expect(css).toContain(`${token}:`)
  })
})
