import { useCallback, useEffect, useState } from 'react'
import { CircleAlert, Play } from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { EvidenceView } from '@/components/EvidenceView'
import { NewReviewDialog } from '@/components/NewReviewDialog'
import { RunPicker } from '@/components/RunPicker'
import { SaveDecisionDialog } from '@/components/SaveDecisionDialog'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { getRun, listRuns } from '@/lib/local-api'
import { useTheme } from '@/lib/use-theme'
import type { Evidence } from '@/types/evidence'
import type { RunSummary } from '@/types/api'

const message = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

export function DevPage() {
  const themeControl = useTheme()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [dialog, setDialog] = useState<{ symbol: string; caseId: string; probeFile: string } | null>(null)

  const refreshRuns = useCallback(() => {
    listRuns().then(setRuns).catch((e: unknown) => setLoadError(message(e, 'Failed to load runs')))
  }, [])

  useEffect(refreshRuns, [refreshRuns])

  async function handleSelectRun(id: string) {
    setSelectedRun(id)
    setLoadError(null)
    setEvidence(null)
    try {
      setEvidence(await getRun(id))
    } catch (e) {
      setLoadError(message(e, 'Failed to load run'))
    }
  }

  function handleReviewDone(id: string) {
    refreshRuns()
    void handleSelectRun(id)
  }

  return (
    <>
      <AppHeader themeControl={themeControl} picker={<RunPicker runs={runs} selectedId={selectedRun} onSelect={handleSelectRun} />}>
        <NewReviewDialog onDone={handleReviewDone} />
      </AppHeader>
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
        {loadError && (
          <Alert variant="destructive">
            <CircleAlert aria-hidden="true" />
            <AlertTitle>The review could not be shown</AlertTitle>
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
        )}
        {evidence && (
          <EvidenceView
            evidence={evidence}
            onSaveDecision={(symbol, caseId, probeFile) => setDialog({ symbol, caseId, probeFile })}
          />
        )}
        {!evidence && !loadError && (
          <Empty className="border">
            <EmptyHeader>
              <EmptyMedia variant="icon"><Play aria-hidden="true" /></EmptyMedia>
              <EmptyTitle>{runs.length ? 'Choose a review' : 'No reviews yet'}</EmptyTitle>
              <EmptyDescription>
                {runs.length
                  ? 'Pick one from the list at the top, or start a new one.'
                  : <>Start one with <strong>New review</strong>: the ref you're merging into and the one with your change.</>}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
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
    </>
  )
}
