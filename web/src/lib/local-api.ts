/**
 * Typed fetch wrappers for the Lane 2 local server API.
 * Source of truth: contracts/local-server-api.md
 * Only imported in local (developer) mode — never bundled into the judge page.
 */
import type { RepoMap } from '@/lib/repo-map'
import type { Evidence } from '@/types/evidence'
import type {
  RunSummary,
  StartRunRequest,
  StartRunResponse,
  DecideRequest,
  DecideResponse,
  GitRef,
  RepoInfo,
  ProgressEvent,
} from '@/types/api'
import { getToken } from '@/lib/mode'

function authHeaders(): HeadersInit {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { ...authHeaders(), ...init?.headers } })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${path} → ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export function listRuns(): Promise<RunSummary[]> {
  return apiFetch<RunSummary[]>('/api/runs')
}

export function getRun(runId: string): Promise<Evidence> {
  return apiFetch<Evidence>(`/api/runs/${encodeURIComponent(runId)}`)
}

export function getRepo(): Promise<RepoInfo> {
  return apiFetch<RepoInfo>('/api/repo')
}

export function listRefs(): Promise<GitRef[]> {
  return apiFetch<GitRef[]>('/api/refs')
}

/** The run's repo map, or null when the run has none. */
export async function getRepoMap(runId: string): Promise<RepoMap | null> {
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/repo_map`, { headers: authHeaders() })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`API /api/runs/${runId}/repo_map → ${res.status}: ${await res.text()}`)
  return res.json() as Promise<RepoMap>
}

export function startRun(body: StartRunRequest): Promise<StartRunResponse> {
  return apiFetch<StartRunResponse>('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function postDecide(body: DecideRequest): Promise<DecideResponse> {
  return apiFetch<DecideResponse>('/api/decide', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function streamProgress(
  runId: string,
  onEvent: (e: ProgressEvent) => void,
  onDone: () => void,
  onError: (err: Event) => void,
): EventSource {
  const token = getToken()
  const url = `/api/runs/${encodeURIComponent(runId)}/progress${token ? `?token=${encodeURIComponent(token)}` : ''}`
  const es = new EventSource(url)
  es.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data as string) as ProgressEvent
      onEvent(event)
      if (event.step === 'done' || event.step === 'error') {
        es.close()
        onDone()
      }
    } catch {
      // ignore malformed events
    }
  }
  es.onerror = (e) => { onError(e); es.close() }
  return es
}
