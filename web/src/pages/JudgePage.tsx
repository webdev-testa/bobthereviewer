import { useState } from 'react'
import { EvidenceView } from '@/components/EvidenceView'
import { evidenceFixture } from '@/fixtures/evidence.fixture'
import type { Evidence } from '@/types/evidence'

// In the judge build, Vite injects __JUDGE_EVIDENCE__ at build time.
// Fallback to the fixture during development.
declare const __JUDGE_EVIDENCE__: Evidence | undefined
const evidence: Evidence =
  typeof __JUDGE_EVIDENCE__ !== 'undefined' ? __JUDGE_EVIDENCE__ : evidenceFixture

export function JudgePage() {
  const [previewVerdict, setPreviewVerdict] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-surface">
      <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-base font-semibold">bobthereviewer</h1>
          <span className="text-xs text-muted">Behavior review report</span>
        </div>

        <EvidenceView
          evidence={evidence}
          onSaveDecision={(symbol, caseId) => setPreviewVerdict(`${symbol}:${caseId}`)}
        />

        {/* Session-only decision preview — no API calls, no file writes */}
        {previewVerdict && (
          <div className="rounded-md border border-warning/40 bg-warning-muted px-4 py-3 text-xs space-y-2">
            <div className="font-medium text-warning">Demo preview — not saved</div>
            <p className="text-muted">
              In the local developer UI, this button saves a decision JSON file and prints a git command.
              On this static page it is for demonstration only.
            </p>
            <button
              onClick={() => setPreviewVerdict(null)}
              className="underline text-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-info rounded"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
