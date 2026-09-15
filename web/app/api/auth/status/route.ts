import { forward } from '@/lib/api/route'

/** Whether this server requires login at all. Lets the login page say so when
 *  Supabase is not configured, instead of failing on the first submit. */
export async function GET() {
  return forward('/auth/status', { anonymous: true })
}
