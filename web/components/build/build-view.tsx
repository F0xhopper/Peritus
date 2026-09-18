'use client'

import { MessageSquare, RotateCcw, X } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { BuildBrain } from '@/components/brain/build-brain'
import { BuildLog } from '@/components/build/build-log'
import { CostPanel } from '@/components/build/cost-panel'
import { StageTimeline } from '@/components/build/stage-timeline'
import { ContextSlot } from '@/components/shell/context-panel'
import { useShell } from '@/components/shell/shell-context'
import { TopBar } from '@/components/shell/top-bar'
import { Button, ButtonLink } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { MenuItem } from '@/components/ui/menu'
import { Notice } from '@/components/ui/notice'
import { useBuildEvents } from '@/hooks/use-build-events'
import { useStartChat } from '@/hooks/use-start-chat'
import { canManage } from '@/lib/access'
import { cn } from '@/lib/cn'

import { STAGE_LABEL } from '@/lib/build/reducer'
import type { BuildStatus, ExpertWithCatalog, StageName } from '@/lib/api/types'
import { useApiAction } from '@/hooks/use-api-action'
import { ClientApiError, apiSend } from '@/lib/api/client'

/**
 * The live build page.
 *
 * The whole page is driven by the durable event log, not by the server render:
 * `status` is only the first paint, and `useBuildEvents` takes over from there
 * and reconnects with a cursor across dropped connections. That is what makes
 * closing the laptop mid-build survivable.
 *
 * Terminal states are rendered distinctly rather than all as "finished",
 * because they mean different things to the person who paid for the build — and
 * the spend-cap case in particular has to say that retrying unchanged will not
 * help, since the money has already been refunded.
 */
export function BuildView({
  expert,
  status,
  creditCost,
}: {
  expert: ExpertWithCatalog
  status: BuildStatus | null
  /** This tier's price in credits, or null where credits are not in force. */
  creditCost: number | null
}) {
  const { openContext } = useShell()
  const router = useRouter()
  const [confirmingCancel, setConfirmingCancel] = useState(false)
  const { start: startChat, starting: startingChat } = useStartChat(expert.name)
  // A viewer can watch the log. Cancelling, rebuilding and the cost of the build
  // are the owner's — the API refuses all three to anyone else.
  const owner = canManage(expert)

  // Already finished before the page loaded: park the hook rather than opening
  // a stream that would close immediately.
  const jobFinished =
    status !== null && ['succeeded', 'failed', 'cancelled'].includes(status.job_status)

  const { state, live, reconnecting, reconnect } = useBuildEvents(expert.name, {
    enabled: status !== null,
  })

  // The stream is the truth while it runs; the server render is the truth
  // before it starts and after it ends. A replayed log of a finished job can
  // hold a `chat_ready` from an attempt whose corpus a later retry wiped, so
  // once the job is over only the expert's own readiness counts.
  const chatReady = jobFinished
    ? expert.readiness !== 'pending'
    : state.chatReady || expert.readiness !== 'pending'
  const noJob = status === null
  const terminal =
    state.terminal ??
    (jobFinished
      ? status.job_status === 'succeeded'
        ? { kind: 'done' as const, message: 'Build finished.' }
        : status.job_status === 'cancelled'
          ? { kind: 'cancelled' as const, message: 'Build cancelled.' }
          : {
              kind: 'error' as const,
              message: status.last_error ?? expert.error ?? 'The build failed.',
              capped: false,
            }
      : null)

  const { run: cancel, pending: cancelling } = useApiAction(
    () =>
      apiSend<{ credits_refunded?: number }>(
        `/api/experts/${encodeURIComponent(expert.name)}/build/cancel`,
        'POST',
        undefined,
        'Could not cancel that build.'
      ),
    {
      success: (body) =>
        body.credits_refunded
          ? `Build cancelled — ${body.credits_refunded} credits refunded.`
          : 'Build cancelled.',
      error: 'Could not cancel that build.',
      onSuccess: () => setConfirmingCancel(false),
      onError: (message, err) => {
        // 409 is not a failure: the build finished while the dialog was open.
        if (err instanceof ClientApiError && err.status === 409) {
          toast.info('That build has already finished.')
          setConfirmingCancel(false)
          router.refresh()
          return
        }
        toast.error(message)
      },
    }
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar
        expert={expert}
        title={terminal || noJob ? 'Build log' : 'Building'}
        action={
          chatReady ? (
            // Starts a conversation and lands in it, composer focused — not the
            // Overview, where the composer is a scroll away.
            <Button
              variant="primary"
              size="action"
              aria-label="Ask now"
              loading={startingChat}
              onClick={() => void startChat()}
              className={cn(
                'shrink-0',
                // One 600ms ring pulse the moment asking becomes possible, then
                // never again — the event that earns attention is the
                // transition, not the state.
                state.chatReady && 'motion-safe:animate-ring-once',
              )}
            >
              <MessageSquare className="size-3.5" />
              <span className="hidden sm:inline">Ask now</span>
            </Button>
          ) : owner && !terminal && !noJob ? (
            <Button
              variant="outline"
              size="action"
              aria-label="Cancel this build"
              onClick={() => setConfirmingCancel(true)}
              className="shrink-0"
            >
              <X className="size-3.5" />
              <span className="hidden sm:inline">Cancel</span>
            </Button>
          ) : undefined
        }
        overflow={
          <>
            <MenuItem onClick={() => router.push(`/experts/${expert.name}`)}>Overview</MenuItem>
            <MenuItem onClick={() => router.push(`/experts/${expert.name}/knowledge`)}>
              Knowledge
            </MenuItem>
            {/* The cost panel is inline only from 1280px; this opens it as an
                overlay or a sheet everywhere below that. */}
            {owner && <MenuItem onClick={openContext}>Cost</MenuItem>}
            {owner && !terminal && !noJob && (
              <MenuItem tone="danger" onClick={() => setConfirmingCancel(true)}>
                Cancel build
              </MenuItem>
            )}
          </>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col gap-3 p-3 md:p-4">
        <StageTimeline stages={state.stages} activeStage={state.activeStage} />

        {/* The brain growing (expert-brain-interactive.md, G3): above the
            timeline below `lg`, where it is a small square; a panel above the
            log from `lg`. The log stays the page's record either way. */}
        {!noJob && (
          <div className="order-first lg:order-none">
            <BuildBrain
              expert={expert}
              grow={state.grow}
              finished={terminal !== null}
              stage={state.activeStage ? (STAGE_LABEL[state.activeStage] ?? null) : null}
            />
          </div>
        )}

        {noJob &&
          (expert.status === 'queued' || expert.status === 'building' ? (
            // The row says a build is coming, and no job exists to run it. Say
            // exactly that — not "no build has run", which contradicted the
            // "Queued" Home showed for the same expert.
            <Notice
              tone="warn"
              title="This build never started"
              action={
                owner ? (
                  <ButtonLink
                    variant="outline"
                    size="sm"
                    href={`/experts/${expert.name}/settings`}
                  >
                    <RotateCcw className="size-3" />
                    Start it again
                  </ButtonLink>
                ) : undefined
              }
            >
              {expert.readiness !== 'pending'
                ? `The expert still answers from its existing sources.${owner ? ' Start the build again from Settings to refresh them.' : ''}`
                : `Nothing was searched.${owner ? ' Start the build again from Settings.' : ''}`}
            </Notice>
          ) : (
            <Notice tone="info" title="No build log for this expert">
              It was built before build logs were kept, so there is nothing to replay here.
            </Notice>
          ))}

        {state.retrying && (
          <Notice tone="warn" title="Retrying">
            The build hit a recoverable error and is starting again. Your credits are still held,
            not spent twice.
          </Notice>
        )}

        {state.degraded.map((degraded) => (
          <Notice
            key={degraded.stage}
            tone="warn"
            title={`${STAGE_LABEL[degraded.stage as StageName] ?? 'One stage'} did not fully finish`}
          >
            {degraded.message}
          </Notice>
        ))}

        {terminal?.kind === 'error' && (
          <Notice
            tone="bad"
            title={terminal.capped ? 'Stopped at the spend cap' : 'The build failed'}
            action={
              !owner ? undefined : terminal.capped ? (
                <ButtonLink
                  variant="outline"
                  size="sm"
                  href={`/experts/${expert.name}/settings`}
                >
                  Rebuild at a different depth
                </ButtonLink>
              ) : (
                <ButtonLink
                  variant="outline"
                  size="sm"
                  href={`/experts/${expert.name}/settings`}
                >
                  <RotateCcw className="size-3" />
                  Rebuild
                </ButtonLink>
              )
            }
          >
            <p>{terminal.message}</p>
            {terminal.capped && (
              <p className="mt-1 text-xs text-fg-3">
                Your credits were refunded in full. Retrying unchanged will hit the same ceiling —
                build at a shallower tier, or narrow the topic.
              </p>
            )}
          </Notice>
        )}

        {terminal?.kind === 'cancelled' && (
          <Notice tone="warn" title="Build cancelled">
            {terminal.message} Any credits held for it were refunded.
          </Notice>
        )}

        {terminal?.kind === 'done' && (
          <Notice
            tone="ok"
            title="Build finished"
            action={
              <Button
                variant="outline"
                size="sm"
                loading={startingChat}
                onClick={() => void startChat()}
              >
                Ask it something
              </Button>
            }
          >
            {terminal.message}
          </Notice>
        )}

        <div className="flex items-center gap-3 text-xs text-fg-3">
          {/* With no job there is nothing counted, and "0 kept · 0 dropped"
              would be a fabricated zero (rule 2), not an empty record. */}
          {!noJob && (
            <span>
              {state.counts.kept} kept · {state.counts.dropped} dropped
              {state.counts.chunks > 0 && ` · ${state.counts.chunks} passages`}
            </span>
          )}
          {live && <span className="text-ok">live</span>}
          {reconnecting && (
            <button
              type="button"
              onClick={reconnect}
              className="text-warn underline-offset-2 hover:underline"
            >
              reconnecting — retry now
            </button>
          )}
        </div>

        {!noJob && (
          <BuildLog
            rows={state.rows}
            live={live}
            reconnecting={reconnecting}
            ended={Boolean(terminal)}
          />
        )}
      </div>

      {/* Cost by stage, once the job has metered anything. Polled by the panel
          itself, because usage lands after the stages that spent it. */}
      {owner && (
        <ContextSlot title="Cost">
          <CostPanel
            slug={expert.name}
            terminal={terminal !== null}
            credits={
              creditCost === null || noJob
                ? null
                : {
                    amount: creditCost,
                    outcome:
                      terminal === null ? 'held' : terminal.kind === 'done' ? 'spent' : 'refunded',
                  }
            }
          />
        </ContextSlot>
      )}

      <Dialog
        open={confirmingCancel}
        onOpenChange={setConfirmingCancel}
        title="Cancel this build?"
        description="Peritus stops the build within a few seconds and refunds the credits held for it in full. Anything already found and screened is kept."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmingCancel(false)}>
              Keep building
            </Button>
            <Button variant="danger" loading={cancelling} onClick={cancel} minWidth={110}>
              Cancel build
            </Button>
          </>
        }
      >
        <p className="text-sm text-fg-3">
          A cancelled build leaves the expert unusable until you rebuild it.
        </p>
      </Dialog>
    </div>
  )
}
