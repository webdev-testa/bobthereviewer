import { useState } from 'react'
import { Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ProgressPanel } from '@/components/ProgressPanel'
import { startRun, streamProgress } from '@/lib/local-api'
import type { ProgressEvent } from '@/types/api'

function RefInput({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (value: string) => void }) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder="branch, tag or commit" />
    </div>
  )
}

export function NewReviewDialog({ onDone }: { onDone: (runId: string) => void }) {
  const [before, setBefore] = useState('')
  const [after, setAfter] = useState('')
  const [runId, setRunId] = useState<string | null>(null)
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [finished, setFinished] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])
  const [error, setError] = useState<string>()

  const reset = () => {
    setRunId(null)
    setEvents([])
    setFinished(false)
    setWarnings([])
    setError(undefined)
  }

  const start = async () => {
    try {
      setError(undefined)
      const { run_id, warnings } = await startRun({ before_ref: before.trim(), after_ref: after.trim(), probes: [] })
      setRunId(run_id)
      setWarnings(warnings)
      streamProgress(
        run_id,
        (event) => setEvents((all) => [...all, event]),
        () => setFinished(true),
        () => setError('Lost the progress stream; the review may still be running.'),
      )
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Dialog onOpenChange={(open) => !open && reset()}>
      <DialogTrigger asChild><Button size="sm"><Play aria-hidden="true" />New review</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New review</DialogTitle>
          <DialogDescription>Runs this repository's tests and probes on this computer, on both revisions.</DialogDescription>
        </DialogHeader>
        {runId ? (
          <div className="space-y-3">
            {warnings.length ? (
              <ul className="space-y-1 rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-xs text-warning">
                {warnings.map((w) => <li key={w}>{w}</li>)}
              </ul>
            ) : null}
            <ProgressPanel events={events} />
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <RefInput id="review-base" label="Base (before)" value={before} onChange={setBefore} />
            <RefInput id="review-head" label="Head (after)" value={after} onChange={setAfter} />
          </div>
        )}
        {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
        <DialogFooter>
          {runId ? (
            <DialogClose asChild>
              <Button disabled={!finished} onClick={() => onDone(runId)}>Show the review</Button>
            </DialogClose>
          ) : (
            <>
              <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
              <Button onClick={() => void start()} disabled={!before.trim() || !after.trim()}>Start review</Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
