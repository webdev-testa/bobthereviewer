/**
 * Pre-publish check for the judge HTML build.
 * Scans dist/judge.html for absolute local paths and token-like strings.
 * Exits non-zero if any are found.
 */
import { readFileSync } from 'fs'
import { resolve } from 'path'

const htmlPath = resolve(import.meta.dirname, '../dist/judge.html')
let html: string
try {
  html = readFileSync(htmlPath, 'utf8')
} catch {
  console.error(`check:judge — cannot read ${htmlPath}. Run npm run build:judge first.`)
  process.exit(1)
}

const issues: string[] = []

// Absolute local paths
const pathPatterns = [/[A-Z]:\\[^"'\s<>]+/g, /\/home\/[^"'\s<>]+/g, /\/Users\/[^"'\s<>]+/g]
for (const pat of pathPatterns) {
  const matches = html.match(pat)
  if (matches) issues.push(`Absolute local path found: ${matches[0]}`)
}

// Token-like strings (40+ char hex, JWT-style, or Bearer tokens)
const tokenPatterns = [
  /\b[0-9a-f]{40,}\b/g,
  /eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}/g,
]
for (const pat of tokenPatterns) {
  const matches = html.match(pat)
  if (matches) issues.push(`Token-like string found: ${matches[0].slice(0, 20)}…`)
}

if (issues.length > 0) {
  console.error('check:judge FAILED:')
  issues.forEach((i) => console.error(' •', i))
  process.exit(1)
}

console.log('check:judge passed — no absolute paths or tokens found.')
