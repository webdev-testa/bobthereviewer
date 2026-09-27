export type Tone = 'danger' | 'warning' | 'success' | 'info' | 'neutral'

// Literal class strings so Tailwind can see them; colors come only from the semantic tokens.
export const TONE_CLASSES: Record<Tone, string> = {
  danger: 'border-danger/40 bg-danger-muted text-danger',
  warning: 'border-warning/40 bg-warning-muted text-warning',
  success: 'border-success/40 bg-success-muted text-success',
  info: 'border-info/40 bg-info-muted text-info',
  neutral: 'border-neutral/40 bg-neutral-muted text-neutral',
}
