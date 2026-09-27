import { CheckCircle2, AlertCircle, Loader2, Circle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ProgressEvent } from '@/types/api'

const STEP_LABELS: Record<string, string> = {
  triage:     'Triage',
  analyze:    'Analyze callers',
  test_base:  'Run tests (base)',
  test_head:  'Run tests (head)',
  probe_base: 'Run probes (base)',
  probe_head: 'Run probes (head)',
  done:       'Done',
  error:      'Error',
}

interface Props { events: ProgressEvent[] }

export function ProgressPanel({ events }: Props) {
  if (events.length === 0) {
    return <div className="text-xs text-muted-foreground p-3">Waiting for run to start…</div>
  }
  // One row per step showing its latest event: a finished step's "started" row used to keep
  // spinning next to its result, so a completed review looked like it was still running.
  const latest = new Map<string, ProgressEvent>()
  events.forEach((e) => latest.set(e.step, e))
  return (
    <div className="space-y-1 p-1">
      {[...latest.values()].map((e) => (
        <div key={e.step} className={cn('flex items-start gap-2 rounded px-2 py-1.5 text-xs', e.status === 'failed' && 'bg-danger-muted')}>
          {e.status === 'completed' && <CheckCircle2 size={13} className="text-success mt-0.5 shrink-0" />}
          {e.status === 'failed'    && <AlertCircle  size={13} className="text-danger mt-0.5 shrink-0" />}
          {e.status === 'started'   && <Loader2      size={13} className="text-info mt-0.5 shrink-0 animate-spin" />}
          {!['completed','failed','started'].includes(e.status) && <Circle size={13} className="text-muted-foreground mt-0.5 shrink-0" />}
          <div>
            <span className="font-medium">{STEP_LABELS[e.step] ?? e.step}</span>
            {e.message && <span className="text-muted-foreground ml-1">{e.message}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}
