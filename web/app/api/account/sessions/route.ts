import { forward } from '@/lib/api/route'

/** The account's signed-in devices. */
export async function GET() {
  return forward('/auth/account/sessions')
}
