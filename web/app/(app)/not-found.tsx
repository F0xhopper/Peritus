import { ButtonLink } from '@/components/ui/button'
import { Empty } from '@/components/ui/empty'
import { FileQuestion } from 'lucide-react'

/**
 * Not found inside the app.
 *
 * Wording matters here: another user's expert 404s rather than 403s, so this
 * page has to cover both "there is nothing at this address" and "this is not
 * yours" without disclosing which.
 */
export default function AppNotFound() {
  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <div className="w-full max-w-sm text-center">
        <Empty icon={FileQuestion}>
          Nothing here. This expert or chat does not exist, or it belongs to someone else.
        </Empty>
        <ButtonLink variant="outline" className="mt-1" href="/experts">
          Back to Home
        </ButtonLink>
      </div>
    </div>
  )
}
