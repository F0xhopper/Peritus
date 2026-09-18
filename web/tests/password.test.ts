import { describe, expect, it } from 'vitest'

import { passwordSchema, passwordStrength } from '@/lib/auth/password'

describe('the password rule (NIST 800-63B, matching the API)', () => {
  it('needs eight characters and nothing else', () => {
    expect(passwordSchema.safeParse('short').success).toBe(false)
    expect(passwordSchema.safeParse('all lowercase words').success).toBe(true)
  })

  it('refuses more than 72 bytes, counting bytes not characters', () => {
    expect(passwordSchema.safeParse('x'.repeat(72)).success).toBe(true)
    expect(passwordSchema.safeParse('x'.repeat(73)).success).toBe(false)
    // 37 two-byte characters is 74 bytes.
    expect(passwordSchema.safeParse('é'.repeat(37)).success).toBe(false)
  })
})

describe('passwordStrength', () => {
  it('rates length above composition', () => {
    expect(passwordStrength('Tr0ub4d!')).toBeLessThan(
      passwordStrength('correct horse battery staple')
    )
  })

  it('never calls a common or email-derived password strong', () => {
    expect(passwordStrength('password1')).toBe(1)
    expect(passwordStrength('ada.lovelace99', 'ada.lovelace@example.com')).toBe(1)
    expect(passwordStrength('aaaaaaaaaaaa')).toBe(1)
  })

  it('is 0 below the minimum', () => {
    expect(passwordStrength('abc')).toBe(0)
  })
})
