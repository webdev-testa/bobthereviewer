import { CircleAlert, CircleCheck, CircleHelp, ExternalLink, MinusCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { StatusBadge } from '@/components/StatusBadge'
import { TriageBadge } from '@/components/TriageBadge'
import { TONE_CLASSES, type Tone } from '@/lib/tones'
import { cn } from '@/lib/utils'
import { reviewVerdict } from '@/lib/verdict'
import type { Evidence, LanguageSupport } from '@/types/evidence'

const VERDICT_ICON: Record<Tone, typeof CircleAlert> = {
  danger: CircleAlert, warning: CircleHelp, success: CircleCheck, info: CircleHelp, neutral: MinusCircle,
}

// Same wording as the PR comment's "Analyzed as" line.
const TIER_TEXT: Record<LanguageSupport['tier'], string> = {
  full: 'full: callers, tests and probes',
  static: 'static: callers only, nothing run',
  static_same_file: 'static, same-file callers only (beta)',
}

function LanguageBadges({ languages }: { languages?: LanguageSupport[] }) {
  const shown = languages?.length ? languages : [{ language: 'Python', tier: 'full' as const }]
  return (
    <>
      {shown.map(({ language, tier }) => (
        <Badge key={language} variant="outline" className={TONE_CLASSES[tier === 'full' ? 'success' : 'neutral']}>
          {language} · {TIER_TEXT[tier]}
        </Badge>
      ))}
    </>
  )
}

function formatTime(iso: string) {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** "https://github.com/owner/repo" → "owner/repo"; anything else is shown as is. */
const repoName = (repository: string) => repository.replace(/^https?:\/\/[^/]+\//, '').replace(/\.git$/, '')

// The GitHub Action reviews exact commits, so its refs are full 40-character SHAs.
const isSha = (ref: string) => /^[0-9a-f]{40}$/i.test(ref)
const shortRef = (ref: string) => (isSha(ref) ? ref.slice(0, 7) : ref)

export function SummaryCard({ evidence }: { evidence: Evidence }) {
  const verdict = reviewVerdict(evidence)
  const Icon = VERDICT_ICON[verdict.tone]
  const refsAreCommits = isSha(evidence.base_ref) && isSha(evidence.head_ref)
  return (
    <Card>
      <CardHeader className="gap-2">
        <p className="text-sm text-muted-foreground">
          Behavior review · {repoName(evidence.repository)} · <time dateTime={evidence.generated_at}>{formatTime(evidence.generated_at)}</time>
        </p>
        <h1 className="flex flex-wrap items-center gap-x-2 text-2xl font-semibold tracking-tight break-all">
          <code>{shortRef(evidence.base_ref)}</code>
          <span aria-hidden="true" className="text-muted-foreground">→</span>
          <code>{shortRef(evidence.head_ref)}</code>
        </h1>
        {/* Commit ids only add something when the title shows branch or tag names. */}
        {refsAreCommits ? null : (
          <p className="text-xs text-muted-foreground">
            <code>{evidence.base_commit.slice(0, 7)}</code> → <code>{evidence.head_commit.slice(0, 7)}</code>
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <div role="status" className={cn('flex items-start gap-2 rounded-md border px-3 py-2 font-medium', TONE_CLASSES[verdict.tone])}>
          <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {verdict.headline}
        </div>
        {verdict.counts.length ? (
          <div className="flex flex-wrap gap-2">
            {verdict.counts.map(([status, count]) => <StatusBadge key={status} status={status} count={count} />)}
          </div>
        ) : null}
      </CardContent>
      <Separator />
      <CardContent className="flex flex-col gap-4 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">Change type</span>
            <TriageBadge triage={evidence.triage} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">Analyzed as</span>
            <LanguageBadges languages={evidence.analysis_limits.languages} />
          </div>
        </div>
        {evidence.ci_run_url?.startsWith('https://') ? (
          <Button asChild variant="outline" size="sm">
            <a href={evidence.ci_run_url} target="_blank" rel="noreferrer">
              GitHub Actions run
              <ExternalLink aria-hidden="true" />
            </a>
          </Button>
        ) : (
          <span className="text-sm text-muted-foreground">Run {evidence.run_id.slice(0, 8)}</span>
        )}
      </CardContent>
    </Card>
  )
}
