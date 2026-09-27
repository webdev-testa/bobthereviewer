/** Returns true when running in local developer mode (token present in URL). */
export function isLocalMode(): boolean {
  const params = new URLSearchParams(window.location.search)
  return params.has('token')
}

/** The review `bobreviewer run --open` asked to show, if any. */
export function requestedRunId(): string | null {
  return new URLSearchParams(window.location.search).get('run')
}

/** Returns the bearer token from the URL, or null in static mode. */
export function getToken(): string | null {
  const params = new URLSearchParams(window.location.search)
  return params.get('token')
}
