import { useState } from 'react'
import { RunList } from '@/components/RunList'
import { ProgressPanel } from '@/components/ProgressPanel'
import { EvidenceView } from '@/components/EvidenceView'
import { SaveDecisionDialog } from '@/components/SaveDecisionDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { getRun, startRun, streamProgress } from '@/lib/local-api'
import type { Evidence } from '@/types/evidence'
import type { ProgressEvent } from '@/types/api'

export function DevPage() {
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [beforeRef, setBeforeRef] = useState('')
  const [afterRef, setAfterRef] = useState('')
  const [running, setRunning] = useState(false)
  const [progressEvents, setProgressEvents] = useState<ProgressEvent[]>([])
  const [dialog, setDialog] = useState<{ symbol: string; caseId: string; probeFile: string } | null>(null)

  async function handleSelectRun(id: string) {
    setSelectedRun(id)
    setLoadError(null)
    setEvidence(null)
    try {
      const ev = await getRun(id)
      setEvidence(ev)
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Failed to load run')
    }
  }

  async function handleStartRun() {
    if (!beforeRef.trim() || !afterRef.trim()) return
    setRunning(true)
    setProgressEvents([])
    try {
      const { run_id } = await startRun({ before_ref: beforeRef, after_ref: afterRef, probes: [] })
      setSelectedRun(run_id)
      streamProgress(
        run_id,
        (e) => setProgressEvents((prev) => [...prev, e]),
        async () => {
          setRunning(false)
          const ev = await getRun(run_id).catch(() => null)
          if (ev) setEvidence(ev)
        },
        () => setRunning(false),
      )
    } catch (e) {
      setRunning(false)
      setLoadError(e instanceof Error ? e.message : 'Failed to start run')
    }
  }

  return (
    <div className="min-h-screen bg-surface flex">
      {/* Sidebar */}
      <aside className="w-64 shrink-0 border-r border-border flex flex-col">
        <div className="px-3 py-3 border-b border-border">
          <div className="text-xs font-semibold mb-2">New review</div>
          <div className="space-y-1.5">
            <Input placeholder="Base ref" value={beforeRef} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setBeforeRef(e.target.value)} className="h-7 text-xs" />
            <Input placeholder="Head ref" value={afterRef} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setAfterRef(e.target.value)} className="h-7 text-xs" />
            <Button size="sm" className="w-full h-7 text-xs" onClick={handleStartRun} disabled={running || !beforeRef || !afterRef}>
              {running ? 'Running…' : 'Start review'}
            </Button>
          </div>
        </div>
        {running && (
          <div className="border-b border-border">
            <ProgressPanel events={progressEvents} />
          </div>
        )}
        <div className="flex-1 overflow-y-auto py-2">
          <div className="px-3 pb-1 text-xs font-semibold text-muted uppercase tracking-wide">History</div>
          <RunList selectedId={selectedRun} onSelect={handleSelectRun} />
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto px-6 py-8 max-w-3xl">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-base font-semibold">bobthereviewer</h1>
          <span className="text-xs text-muted">Developer UI</span>
        </div>
        <Separator className="mb-6" />
        {loadError && <p className="text-xs text-danger">{loadError}</p>}
        {evidence && (
          <EvidenceView
            evidence={evidence}
            onSaveDecision={(symbol, caseId, probeFile) => setDialog({ symbol, caseId, probeFile })}
          />
        )}
        {!evidence && !loadError && (
          <p className="text-xs text-muted">Select a run from the sidebar or start a new one.</p>
        )}
      </main>

      {dialog && selectedRun && (
        <SaveDecisionDialog
          open
          runId={selectedRun}
          symbol={dialog.symbol}
          caseId={dialog.caseId}
          probeFile={dialog.probeFile}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  )
}
