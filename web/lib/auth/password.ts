import { z } from '@/lib/validation'

/**
 * The password rule, and an advisory strength estimate.
 *
 * The rule is NIST SP 800-63B §5.1.1.2 and matches the API's
 * (`api/schemas/auth.py`): at least 8 characters, at most 72 bytes — bcrypt's
 * limit, past which two different passwords hash the same — and nothing else.
 * No "one uppercase, one symbol": composition rules push people to
 * `Password1!`, which every cracking list already has.
 *
 * The meter only advises. What actually refuses a known-breached password is
 * Supabase's leaked-password check, when the project has it on.
 */

export const PASSWORD_MIN = 8
export const PASSWORD_MAX_BYTES = 72

export const passwordSchema = z
  .string()
  .min(PASSWORD_MIN, `Use at least ${PASSWORD_MIN} characters`)
  .refine(
    (value) => new TextEncoder().encode(value).length <= PASSWORD_MAX_BYTES,
    'That is too long — keep it under 72 characters'
  )

// The handful everyone tries first. Not a breach list — just enough that the
// meter never calls `password1` strong.
const COMMON = new Set([
  'password',
  'password1',
  'password123',
  '12345678',
  '123456789',
  '1234567890',
  'qwertyuiop',
  'qwerty123',
  'iloveyou',
  'letmein1',
  'welcome1',
  'admin123',
  'abc12345',
  'football',
  'baseball',
  'sunshine',
  'princess',
  'trustno1',
  'passw0rd',
  'peritus1',
])

export type Strength = 0 | 1 | 2 | 3 | 4

export const STRENGTH_LABEL: Record<Strength, string> = {
  0: 'Too short',
  1: 'Weak',
  2: 'Fair',
  3: 'Good',
  4: 'Strong',
}

/**
 * 0–4. Length does most of the work, as it does for an attacker: a long
 * passphrase of lowercase words scores well, a short "complex" string does not.
 */
export function passwordStrength(value: string, email?: string | null): Strength {
  if (value.length < PASSWORD_MIN) return 0
  const lower = value.toLowerCase()
  if (COMMON.has(lower)) return 1
  const local = email?.split('@')[0]?.toLowerCase()
  if (local && local.length >= 3 && lower.includes(local)) return 1
  // One character repeated, or a straight run, is a single guess.
  if (/^(.)\1+$/.test(value) || '0123456789abcdefghijklmnopqrstuvwxyz'.includes(lower)) return 1

  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((re) => re.test(value)).length
  const unique = new Set(value).size

  let score = 1
  if (value.length >= 12) score += 1
  if (value.length >= 16) score += 1
  if (classes >= 3 || (value.length >= 12 && classes >= 2)) score += 1
  if (unique < value.length / 3) score -= 1
  return Math.max(1, Math.min(4, score)) as Strength
}
