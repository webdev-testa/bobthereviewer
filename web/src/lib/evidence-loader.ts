/**
 * Mode-aware evidence loader.
 * Static mode: returns the evidence injected at build time.
 * Local mode: fetches from the Lane 2 API.
 */
import { useEffect, useState } from 'react'
import type { Evidence } from '@/types/evidence'
import { isLocalMode, getToken } from '@/lib/mode'
import { getRun } from '@/lib/local-api'

declare const __JUDGE_EVIDENCE__: Evidence | undefined

export function useEvidence(runId?: string): {
  evidence: Evidence | null
  loading: boolean
  error: string | null
} {
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isLocalMode()) {
      // Static mode — evidence injected by Vite at build time
      const injected = typeof __JUDGE_EVIDENCE__ !== 'undefined' ? __JUDGE_EVIDENCE__ : null
      setEvidence(injected)
      setLoading(false)
      return
    }

    if (!runId) {
      setLoading(false)
      return
    }

    if (!getToken()) {
      setError('No token in URL. Open this page via bobreviewer ui.')
      setLoading(false)
      return
    }

    getRun(runId)
      .then((e) => { setEvidence(e); setLoading(false) })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load evidence')
        setLoading(false)
      })
  }, [runId])

  return { evidence, loading, error }
}
