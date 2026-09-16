import { describe, expect, it } from 'vitest'

import { describeChannelStatus } from '@/lib/selection'

describe('failed channels', () => {
  it('phrases the statuses the way the build log does', () => {
    expect(describeChannelStatus('timeout')).toBe('timed out')
    expect(describeChannelStatus('rate_limited')).toBe('rate-limited')
    expect(describeChannelStatus('error')).toBe('failed')
    expect(describeChannelStatus('brand_new')).toBe('brand new')
  })
})
