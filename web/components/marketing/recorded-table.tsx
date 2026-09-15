import { cn } from '@/lib/cn'

/**
 * "What gets recorded", as a table.
 *
 * Deliberately the same shape as the ledger the app renders — 28px rows, a
 * `--border-soft` divider per row, a sticky-able header in label case — inside
 * its own `overflow-x-auto` container, which is the only way anything on this
 * site is allowed to scroll sideways.
 */
const ROWS: { question: string; recorded: string }[] = [
  {
    question: 'What did it find?',
    recorded: 'Every candidate, per source type, per search — with the query count',
  },
  {
    question: 'What did it keep?',
    recorded: 'Quality and relevance scores, the rubric version, and the model that judged them',
  },
  {
    question: 'What did it throw away?',
    recorded: 'Every rejected source with its scores and the stated reason',
  },
  {
    question: 'How much of each source did it read?',
    recorded: 'Full text, an OCR’d PDF, a landing page, or the abstract alone',
  },
  {
    question: 'Why did this search run?',
    recorded: 'The discovery path — the plan, a citation followed, or a concept with no coverage',
  },
  {
    question: 'Was a decision made twice?',
    recorded: 'The first-pass scores, the reviewing model, and whether the verdict reversed',
  },
  {
    question: 'Where did it stop, and why?',
    recorded: 'Rounds run, coverage per concept, and the stated stop reason',
  },
  {
    question: 'What did the answer use?',
    recorded: 'Which retrieved passages reached the prompt, and which the answer cited',
  },
  {
    question: 'What did it cost?',
    recorded: 'Metered provider spend per stage, against the build’s cap',
  },
]

export function RecordedTable({ className }: { className?: string }) {
  return (
    <div className={cn('overflow-x-auto rounded-card border border-border bg-panel', className)}>
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr>
            <th
              scope="col"
              className="border-b border-border px-3 py-2 text-left text-label tracking-[0.04em] text-fg-3 uppercase"
            >
              Question
            </th>
            <th
              scope="col"
              className="border-b border-border px-3 py-2 text-left text-label tracking-[0.04em] text-fg-3 uppercase"
            >
              What is recorded
            </th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => (
            <tr key={row.question} className="transition-colors duration-(--dur-1) hover:bg-raised">
              <td className="border-b border-border-soft px-3 py-2 align-top text-fg-2">
                {row.question}
              </td>
              <td className="border-b border-border-soft px-3 py-2 align-top text-fg-3">
                {row.recorded}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
