import { describe, expect, it } from 'vitest'

import {
  firstSentence,
  formatBytes,
  formatClock,
  formatCredits,
  formatDate,
  formatDateTime,
  formatElapsed,
  formatNumber,
  formatInt,
  formatPercent,
  formatUsd,
  hostOf,
  humanise,
  notRecorded,
  truncate,
} from '@/lib/format'
import { dotState } from '@/components/ui/status-dot'

/**
 * Formatting, and the readiness gate.
 *
 * The whole reason these are tested is one rule from audit-api.md: **`null`
 * means "not recorded", never zero.** Every count the system does not persist
 * comes back as null with a reason, and a helper that quietly coerced null to 0
 * would put a fabricated number into an evidence record — which is worse than a
 * visible gap. Each formatter therefore has an explicit null case.
 */

const DASH = notRecorded()

describe('null is never rendered as zero', () => {
  it('holds for every numeric formatter', () => {
    for (const format of [formatNumber, formatPercent, formatUsd, formatCredits]) {
      expect(format(null)).toBe(DASH)
      expect(format(undefined)).toBe(DASH)
    }
  })

  it('but a genuine zero is rendered as zero', () => {
    // A corpus that truly accepted nothing must say 0, not "not recorded".
    expect(formatNumber(0)).toBe('0')
    expect(formatPercent(0)).toBe('0%')
    expect(formatUsd(0)).toBe('$0.00')
    expect(formatCredits(0)).toBe('0 credits')
  })
})

describe('dates are formatted without Intl', () => {
  /**
   * These exist because of one production failure, not for coverage.
   *
   * `toLocaleDateString('en-GB', { month: 'short' })` disagrees between
   * engines — Node and Chromium's ICU say "Sept", WebKit's says "Sep" — so a
   * date rendered on the server and hydrated in iOS Safari was a React #418
   * text mismatch, which discards the server HTML for the subtree and in
   * practice broke the expert page outright. The month names are written out
   * in `lib/format.ts` for that reason, and an assertion on the exact string
   * is what stops someone reaching for `Intl` again.
   */
  it('spells every month with three letters', () => {
    const months = Array.from({ length: 12 }, (_, month) =>
      formatDate(new Date(new Date().getFullYear(), month, 8).toISOString())
    )
    expect(months).toEqual([
      '8 Jan',
      '8 Feb',
      '8 Mar',
      '8 Apr',
      '8 May',
      '8 Jun',
      '8 Jul',
      '8 Aug',
      '8 Sep',
      '8 Oct',
      '8 Nov',
      '8 Dec',
    ])
  })

  it('adds the year only when it is not this one', () => {
    const year = new Date().getFullYear()
    expect(formatDate(new Date(year, 8, 8).toISOString())).toBe('8 Sep')
    expect(formatDate(new Date(year - 2, 8, 8).toISOString())).toBe(`8 Sep ${year - 2}`)
  })

  it('pads the clock parts, so a log column does not jitter', () => {
    const at = new Date(new Date().getFullYear(), 8, 8, 9, 5, 3).toISOString()
    expect(formatDateTime(at)).toBe('8 Sep, 09:05')
    expect(formatClock(at)).toBe('09:05:03')
  })

  it('renders an unparseable instant as not recorded, never as an epoch', () => {
    expect(formatDate('not a date')).toBe(DASH)
    expect(formatDateTime('not a date')).toBe(DASH)
    expect(formatClock('not a date')).toBe('--:--:--')
  })
})

describe('formatUsd', () => {
  it('shows cents for ordinary amounts', () => {
    expect(formatUsd(1.6)).toBe('$1.60')
    expect(formatUsd(12.005)).toBe('$12.01')
  })

  it('shows four places for a sub-cent amount rather than $0.00', () => {
    // Per-stage build spend is routinely fractions of a cent, and rounding it
    // to zero would make a cost panel read as free.
    expect(formatUsd(0.0031)).toBe('$0.0031')
    expect(formatUsd(-0.0031)).toBe('$-0.0031')
  })
})

describe('formatPercent', () => {
  it('takes a fraction, as the API returns one', () => {
    expect(formatPercent(0.4468)).toBe('45%')
    expect(formatPercent(0.4468, 1)).toBe('44.7%')
    expect(formatPercent(1)).toBe('100%')
  })

  it('renders a negative estimator error with its sign', () => {
    expect(formatPercent(-0.4, 1)).toBe('-40.0%')
  })
})

describe('formatCredits', () => {
  it('pluralises, including for a negative clawback', () => {
    expect(formatCredits(1)).toBe('1 credit')
    expect(formatCredits(3)).toBe('3 credits')
    expect(formatCredits(-1)).toBe('-1 credit')
  })
})

describe('formatElapsed', () => {
  it('drops the unit that is zero', () => {
    expect(formatElapsed(42)).toBe('42s')
    expect(formatElapsed(125)).toBe('2m 5s')
    expect(formatElapsed(3725)).toBe('1h 2m')
  })

  it('refuses nonsense rather than printing NaN', () => {
    expect(formatElapsed(Number.NaN)).toBe(DASH)
    expect(formatElapsed(-5)).toBe(DASH)
  })
})

describe('formatBytes', () => {
  it('picks a readable unit', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(20 * 1024 * 1024)).toBe('20.0 MB')
  })
})

describe('humanise', () => {
  it('turns a machine value into a label', () => {
    expect(humanise('chat_ready')).toBe('Chat ready')
    expect(humanise('oa_pdf_ocr')).toBe('Oa pdf ocr')
    expect(humanise('graph-extraction')).toBe('Graph extraction')
  })

  it('renders an absent value as not-recorded, not as an empty string', () => {
    expect(humanise(null)).toBe(DASH)
    expect(humanise('')).toBe(DASH)
  })
})

describe('truncate', () => {
  it('leaves a short string alone', () => {
    expect(truncate('short', 20)).toBe('short')
  })

  it('cuts at a word boundary when there is a sensible one', () => {
    expect(truncate('gapfill:measurement error in cohorts', 24)).toBe('gapfill:measurement…')
  })

  it('cuts mid-word rather than losing most of the string', () => {
    // A boundary before 60% of the limit would throw away too much.
    expect(truncate('averyverylongsinglewordindeed', 10)).toBe('averyveryl…')
  })
})

describe('hostOf', () => {
  it('strips the scheme and www', () => {
    expect(hostOf('https://www.example.org/a/b?c=d')).toBe('example.org')
    expect(hostOf('http://sub.example.org')).toBe('sub.example.org')
  })

  it('returns null rather than throwing on a non-URL', () => {
    expect(hostOf('not a url')).toBeNull()
    expect(hostOf(null)).toBeNull()
    expect(hostOf('')).toBeNull()
  })
})

describe('the readiness gate', () => {
  it('reports an expert as answerable from chat_ready, while it is still building', () => {
    // The rule the whole product hangs on: gate on readiness, not status. An
    // expert whose chunks are embedded answers a full stage before its job
    // finishes, and reading `status` would hide a working expert.
    expect(dotState('building', 'chat_ready')).toBe('chat-ready')
    expect(dotState('building', 'graph_ready')).toBe('chat-ready')
  })

  it('reports a pending expert as building, not answerable', () => {
    expect(dotState('building', 'pending')).toBe('building')
    expect(dotState('queued', 'pending')).toBe('queued')
  })

  it('lets failure win over any readiness', () => {
    // A cancelled or failed build leaves a corpus nobody should be offered.
    expect(dotState('failed', 'chat_ready')).toBe('failed')
    expect(dotState('failed', 'pending')).toBe('failed')
  })

  it('reports a finished expert as ready', () => {
    expect(dotState('ready', 'graph_ready')).toBe('ready')
    // A spend cap that fired after chat-ready publishes the expert as ready.
    expect(dotState('ready', 'chat_ready')).toBe('ready')
  })

  it('falls back to status alone when readiness is unknown', () => {
    expect(dotState('building')).toBe('building')
    expect(dotState('ready')).toBe('ready')
  })
})

describe('formatElapsed over a day', () => {
  it('switches to days, so a stalled counter does not read as 117 hours', () => {
    expect(formatElapsed(117 * 3600 + 54 * 60)).toBe('4d 21h')
  })
})

describe('formatInt', () => {
  /**
   * Written out rather than delegated to `toLocaleString`: `Intl` is not stable
   * across engines, and a number rendered on the server has to match the one the
   * browser hydrates over.
   */
  it('groups thousands', () => {
    expect(formatInt(0)).toBe('0')
    expect(formatInt(999)).toBe('999')
    expect(formatInt(1000)).toBe('1,000')
    expect(formatInt(1125)).toBe('1,125')
    expect(formatInt(1234567)).toBe('1,234,567')
  })

  it('keeps a negative sign outside the grouping', () => {
    expect(formatInt(-1234)).toBe('-1,234')
  })
})

describe('firstSentence', () => {
  it('does not stop at a title', () => {
    expect(firstSentence('Dr. Marisol Cheng studies epigenetics. She reads widely.')).toBe(
      'Dr. Marisol Cheng studies epigenetics.'
    )
  })

  it('does not stop at an initial or an abbreviation', () => {
    expect(firstSentence('A reader of J. S. Bach, e.g. the cantatas. More.')).toBe(
      'A reader of J. S. Bach, e.g. the cantatas.'
    )
  })

  it('ends on a question or exclamation mark', () => {
    expect(firstSentence('Why bees? Because.')).toBe('Why bees?')
  })

  it('keeps text with no terminator whole', () => {
    expect(firstSentence('  Dr. Cheng  ')).toBe('Dr. Cheng')
    expect(firstSentence('')).toBeNull()
  })
})
