import { useState } from 'react'
import { Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ProgressPanel } from '@/components/ProgressPanel'
import { getRepo, listRefs, startRun, streamProgress } from '@/lib/local-api'
import type { GitRef, ProgressEvent } from '@/types/api'

const REF_GROUPS: [GitRef['kind'], string][] = [['branch', 'Branches'], ['remote', 'Remote branches'], ['tag', 'Tags']]

function RefSelect({ id, label, value, refs, onChange }: {
  id: string; label: string; value: string; refs: GitRef[]; onChange: (value: string) => void
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} className="w-full"><SelectValue placeholder="Choose a branch or tag" /></SelectTrigger>
        <SelectContent>
          {REF_GROUPS.map(([kind, title]) => {
            const group = refs.filter((r) => r.kind === kind)
            return group.length ? (
              <SelectGroup key={kind}>
                <SelectLabel>{title}</SelectLabel>
                {group.map((r) => <SelectItem key={`${kind}:${r.name}`} value={r.name}>{r.name} · {r.sha}</SelectItem>)}
              </SelectGroup>
            ) : null
          })}
        </SelectContent>
      </Select>
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
  const [refs, setRefs] = useState<GitRef[]>([])

  const reset = () => {
    setRunId(null)
    setEvents([])
    setFinished(false)
    setWarnings([])
    setError(undefined)
  }

  // Defaults: base = the configured base branch, head = the branch checked out now.
  const load = async () => {
    try {
      const [repo, all] = await Promise.all([getRepo(), listRefs()])
      setRefs(all)
      const names = new Set(all.map((r) => r.name))
      setBefore((current) => current || (names.has(repo.base_branch) ? repo.base_branch : ''))
      setAfter((current) => current || (repo.branch !== 'HEAD' && names.has(repo.branch) ? repo.branch : ''))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    }
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
    <Dialog onOpenChange={(open) => (open ? void load() : reset())}>
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
            <RefSelect id="review-base" label="Base (before)" value={before} refs={refs} onChange={setBefore} />
            <RefSelect id="review-head" label="Head (after)" value={after} refs={refs} onChange={setAfter} />
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
