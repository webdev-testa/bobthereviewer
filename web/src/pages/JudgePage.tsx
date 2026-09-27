import { useState } from 'react'
import { Eye } from 'lucide-react'
import { AppHeader } from '@/components/AppHeader'
import { EvidenceView } from '@/components/EvidenceView'
import { TONE_CLASSES } from '@/lib/tones'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { evidenceFixture } from '@/fixtures/evidence.fixture'
import { useTheme } from '@/lib/use-theme'
import type { Evidence } from '@/types/evidence'

// In the judge build, Vite injects __JUDGE_EVIDENCE__ at build time.
// Fallback to the fixture during development.
declare const __JUDGE_EVIDENCE__: Evidence | undefined
const evidence: Evidence =
  typeof __JUDGE_EVIDENCE__ !== 'undefined' ? __JUDGE_EVIDENCE__ : evidenceFixture

export function JudgePage() {
  const themeControl = useTheme()
  const [previewTarget, setPreviewTarget] = useState<string | null>(null)

  return (
    <>
      <AppHeader themeControl={themeControl} />
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
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
              <Button variant="outline" size="sm" onClick={() => setPreviewTarget(null)}>Dismiss</Button>
            </AlertDescription>
          </Alert>
        )}
        <EvidenceView
          evidence={evidence}
          onSaveDecision={(symbol, caseId) => setPreviewTarget(`${symbol}:${caseId}`)}
        />
      </main>
    </>
  )
}
