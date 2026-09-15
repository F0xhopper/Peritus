import { forward } from '@/lib/api/route'

export async function GET() {
  return forward('/billing/me')
}
