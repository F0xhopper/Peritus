import { forward, pickParams, query } from '@/lib/api/route'

export async function GET(request: Request) {
  const q = query(pickParams(request.url, ['limit']))
  return forward(`/conversations${q}`)
}
