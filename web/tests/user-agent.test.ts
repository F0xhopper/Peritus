import { describe, expect, it } from 'vitest'

import { describeUserAgent } from '@/lib/user-agent'

describe('describeUserAgent', () => {
  it.each([
    [
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
      'Safari on macOS',
    ],
    [
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 Edg/140.0',
      'Edge on Windows',
    ],
    [
      'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/140.0 Mobile/15E148 Safari/604.1',
      'Chrome on iPhone',
    ],
    ['Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0', 'Firefox on Linux'],
    ['python-httpx/0.28.1', 'Terminal app, or an older sign-in'],
    [null, 'Unknown device'],
    ['curl/8.0', 'Unknown device'],
  ])('%s → %s', (agent, label) => {
    expect(describeUserAgent(agent).label).toBe(label)
  })

  it('knows a phone', () => {
    expect(
      describeUserAgent(
        'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36'
      ).kind
    ).toBe('phone')
  })
})
