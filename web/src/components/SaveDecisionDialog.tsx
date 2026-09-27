import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { postDecide } from '@/lib/local-api'
import type { DecideRequest } from '@/types/api'

interface Props {
  open: boolean
  runId: string
  symbol: string
  caseId: string
  probeFile: string
  onClose: () => void
}

export function SaveDecisionDialog({ open, runId, symbol, caseId, probeFile, onClose }: Props) {
  const [verdict, setVerdict] = useState<DecideRequest['verdict'] | ''>('')
  const [rationale, setRationale] = useState('')
  const [result, setResult] = useState<{ file_path: string; git_command: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const isIntended = verdict === 'intended'
  const canSubmit = verdict !== '' && (!isIntended || rationale.trim().length > 0)

  async function handleSave() {
    if (!verdict) return
    setSaving(true)
    setError(null)
    try {
      const res = await postDecide({ run_id: runId, symbol, case_id: caseId, probe_file: probeFile, verdict, rationale })
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(open_: boolean) => !open_ && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-sm">Save decision — {symbol}</DialogTitle>
        </DialogHeader>
        {result ? (
          <div className="space-y-2 text-sm">
            <div className="text-success">Decision saved.</div>
            <div className="font-mono text-xs bg-surface-raised rounded px-2 py-1">{result.file_path}</div>
            <div className="font-mono text-xs bg-surface-raised rounded px-2 py-1">{result.git_command}</div>
            <Button size="sm" onClick={onClose}>Close</Button>
          </div>
        ) : (
          <>
            <div className="space-y-3">
              <Select value={verdict} onValueChange={(v: string) => setVerdict(v as DecideRequest['verdict'])}>
                <SelectTrigger className="text-sm"><SelectValue placeholder="Verdict" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="intended">Intended</SelectItem>
                  <SelectItem value="unintended">Unintended</SelectItem>
                  <SelectItem value="unresolved">Unresolved</SelectItem>
                </SelectContent>
              </Select>
              <textarea
                className="w-full rounded-md border border-border bg-surface text-sm px-3 py-2 focus-visible:ring-2 focus-visible:ring-info outline-none resize-none"
                rows={3}
                placeholder={isIntended ? 'Rationale (required for Intended)' : 'Rationale (optional)'}
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
              />
              {isIntended && rationale.trim().length === 0 && (
                <p className="text-xs text-danger">Rationale is required for an Intended verdict.</p>
              )}
              {error && <p className="text-xs text-danger">{error}</p>}
            </div>
            <DialogFooter>
              <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
              <Button size="sm" onClick={handleSave} disabled={!canSubmit || saving}>
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
