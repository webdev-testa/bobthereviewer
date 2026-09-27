import type { LucideIcon } from 'lucide-react'
import { CircleCheck, FileQuestion, Layers, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { TONE_CLASSES, type Tone } from '@/lib/tones'
import type { TriageInfo } from '@/types/evidence'

const CONFIG: Record<string, { label: string; icon: LucideIcon; tone: Tone }> = {
  'code':               { label: 'Code change',        icon: Layers,        tone: 'info' },
  'tests-only':         { label: 'Tests only',         icon: CircleCheck,   tone: 'neutral' },
  'docs-only':          { label: 'Docs only',          icon: FileQuestion,  tone: 'neutral' },
  'config-deps':        { label: 'Config / deps',      icon: TriangleAlert, tone: 'warning' },
  'no-semantic-change': { label: 'No semantic change', icon: CircleCheck,   tone: 'neutral' },
}

interface Props { triage: TriageInfo }

export function TriageBadge({ triage }: Props) {
  const { label, icon: Icon, tone } = CONFIG[triage.category] ?? { label: triage.category, icon: FileQuestion, tone: 'neutral' }
  return (
    <>
      <Badge variant="outline" className={TONE_CLASSES[tone]}>
        <Icon aria-hidden="true" />{label}
      </Badge>
      {triage.skipped && (
        <Badge variant="outline" className={TONE_CLASSES.warning}>
          <TriangleAlert aria-hidden="true" />Execution skipped — {triage.skip_reason ?? 'docs-only diff'}
        </Badge>
      )}
    </>
  )
}
