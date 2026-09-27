import { useMemo, useState } from 'react'
import { Eye, ExternalLink, GitPullRequest, PlayCircle } from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { EvidenceView } from '@/components/EvidenceView'
import { TONE_CLASSES } from '@/lib/tones'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { evidenceFixture } from '@/fixtures/evidence.fixture'
import { DecisionContext } from '@/lib/decision-context'
import { useTheme } from '@/lib/use-theme'
import type { Evidence } from '@/types/evidence'
import type { RepoMap } from '@/lib/repo-map'

export interface JudgePrEntry {
  id: string
  pr: number
  title: string
  label: string
  pr_url: string
  run_url: string
  evidence: Evidence
  repoMap: RepoMap | null
}

declare const __JUDGE_PRS__: JudgePrEntry[] | undefined

const defaultEntries: JudgePrEntry[] = [
  {
    id: 'fixture',
    pr: 0,
    title: 'Fixture Review',
    label: 'Fixture Review (dev fallback)',
    pr_url: '',
    run_url: '',
    evidence: evidenceFixture,
    repoMap: null,
  },
]

const prsList: JudgePrEntry[] =
  typeof __JUDGE_PRS__ !== 'undefined' && __JUDGE_PRS__.length > 0
    ? __JUDGE_PRS__
    : defaultEntries

export function JudgePage() {
  const themeControl = useTheme()
  const [previewTarget, setPreviewTarget] = useState<string | null>(null)

  const [selectedPrId, setSelectedPrId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const urlPr = new URLSearchParams(window.location.search).get('pr')
      if (urlPr && prsList.some((p) => p.id === urlPr)) {
        return urlPr
      }
    }
    // Default to the last PR entry
    return prsList[prsList.length - 1].id
  })

  const currentPr = useMemo(() => {
    return prsList.find((p) => p.id === selectedPrId) || prsList[prsList.length - 1]
  }, [selectedPrId])

  const handleSelectPr = (id: string) => {
    setSelectedPrId(id)
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href)
      url.searchParams.set('pr', id)
      window.history.replaceState({}, '', url.toString())
    }
  }

  // The static page never writes anything: Save decision only shows the preview notice.
  const decisionActions = useMemo(
    () => ({
      save: (symbol: string, caseId: string) => setPreviewTarget(`${symbol}:${caseId}`),
      saved: new Set<string>(),
    }),
    []
  )

  return (
    <>
      <AppHeader themeControl={themeControl} />
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
        {/* PR Selection bar */}
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4 shadow-xs">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium text-muted-foreground">Select PR:</span>
            <Select value={currentPr.id} onValueChange={handleSelectPr}>
              <SelectTrigger className="w-[300px] sm:w-[380px]">
                <SelectValue placeholder="Select a PR..." />
              </SelectTrigger>
              <SelectContent>
                {prsList.map((pr) => (
                  <SelectItem key={pr.id} value={pr.id}>
                    {pr.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-4 text-sm">
            {currentPr.pr_url && (
              <a
                href={currentPr.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground underline underline-offset-4 transition-colors"
              >
                <GitPullRequest className="size-4" />
                <span>Pull Request {currentPr.pr ? `#${currentPr.pr}` : ''}</span>
                <ExternalLink className="size-3" />
              </a>
            )}
            {currentPr.run_url && (
              <a
                href={currentPr.run_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground underline underline-offset-4 transition-colors"
              >
                <PlayCircle className="size-4" />
                <span>Action Run</span>
                <ExternalLink className="size-3" />
              </a>
            )}
          </div>
        </div>

        {/* Session-only decision preview — no API calls, no file writes */}
        {previewTarget && (
          <Alert className={TONE_CLASSES.warning}>
            <Eye aria-hidden="true" />
            <AlertTitle>Demo preview — not saved</AlertTitle>
            <AlertDescription className="space-y-2">
              <p>
                In the local developer UI, this button saves a decision JSON file and prints a git command.
                On this static page it is for demonstration only.
              </p>
              <Button variant="outline" size="sm" onClick={() => setPreviewTarget(null)}>
                Dismiss
              </Button>
            </AlertDescription>
          </Alert>
        )}

        <DecisionContext.Provider value={decisionActions}>
          <EvidenceView key={currentPr.id} evidence={currentPr.evidence} repoMap={currentPr.repoMap} />
        </DecisionContext.Provider>
      </main>
    </>
  )
}
