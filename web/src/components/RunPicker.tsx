import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { RunSummary } from '@/types/api'

function runLabel(run: RunSummary) {
  const time = new Date(run.generated_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  return `${run.base_ref} → ${run.head_ref} · ${time}`
}

interface Props { runs: RunSummary[]; selectedId: string | null; onSelect: (id: string) => void }

export function RunPicker({ runs, selectedId, onSelect }: Props) {
  if (!runs.length) return null
  return (
    <Select value={selectedId ?? undefined} onValueChange={onSelect}>
      <SelectTrigger aria-label="Review to show" className="w-full min-w-0 sm:w-auto sm:max-w-96">
        <SelectValue placeholder="Choose a review" />
      </SelectTrigger>
      <SelectContent>
        {runs.map((run) => <SelectItem key={run.run_id} value={run.run_id}>{runLabel(run)}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}
