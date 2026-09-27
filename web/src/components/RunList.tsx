import { useEffect, useState } from 'react'
import { GitCompare, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { listRuns } from '@/lib/local-api'
import type { RunSummary } from '@/types/api'

interface Props { selectedId: string | null; onSelect: (id: string) => void }

export function RunList({ selectedId, onSelect }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listRuns()
      .then(setRuns)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load runs'))
  }, [])

  if (error) return <div className="text-xs text-danger p-3">{error}</div>
  if (runs.length === 0) return <div className="text-xs text-muted p-3">No saved runs yet.</div>

  return (
    <div className="space-y-0.5">
      {runs.map((r) => (
        <button
          key={r.run_id}
          onClick={() => onSelect(r.run_id)}
          className={cn(
            'w-full text-left px-3 py-2 rounded-md text-xs hover:bg-surface-raised transition-colors focus-visible:ring-2 focus-visible:ring-info outline-none',
            selectedId === r.run_id && 'bg-surface-raised font-medium',
          )}
        >
          <div className="flex items-center gap-1.5">
            <GitCompare size={12} className="text-muted shrink-0" />
            <span className="truncate font-mono">{r.base_ref} → {r.head_ref}</span>
          </div>
          <div className="flex items-center gap-1 text-muted mt-0.5">
            <Clock size={11} />
            <span>{new Date(r.generated_at).toLocaleString()}</span>
          </div>
        </button>
      ))}
    </div>
  )
}
