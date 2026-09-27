/**
 * Pre-publish check for the judge HTML build.
 * Scans dist-judge/index.html for absolute local paths and token-like strings.
 * Exits non-zero if any are found.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const htmlPath = resolve(import.meta.dirname, '../dist-judge/index.html')
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

// Collect legitimate commit SHAs and suite/probe hashes from inlined evidence so they aren't misflagged
const allowedHex = new Set<string>()

// 1. From JUDGE_PRS directory if available
const judgePrs = process.env.JUDGE_PRS
if (judgePrs) {
  const prsDir = resolve(process.cwd(), judgePrs)
  if (existsSync(prsDir)) {
    const collectFromDir = (dir: string) => {
      for (const entry of readdirSync(dir)) {
        const full = join(dir, entry)
        if (statSync(full).isDirectory()) {
          collectFromDir(full)
        } else if (entry.endsWith('.json')) {
          try {
            const content = readFileSync(full, 'utf8')
            const hexMatches = content.matchAll(/\b[0-9a-fA-F]{40,64}\b/g)
            for (const m of hexMatches) {
              allowedHex.add(m[0].toLowerCase())
            }
          } catch {
            // ignore
          }
        }
      }
    }
    collectFromDir(prsDir)
  }
}

// 2. From HTML evidence / repo map structure
const keyPatterns = [
  /(?:base_commit|head_commit|frozen_suite_hash|probe_hash|sha)\s*[:=]\s*[`"']?([0-9a-fA-F]{40,64})[`"']?/gi,
  /"(?:base_commit|head_commit|frozen_suite_hash|probe_hash|sha)":\s*"([0-9a-fA-F]{40,64})"/gi,
]
for (const pat of keyPatterns) {
  for (const m of html.matchAll(pat)) {
    allowedHex.add(m[1].toLowerCase())
  }
}

// Token-like strings (JWT-style or Bearer tokens)
const jwtMatches = html.match(/eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}/g) || []
for (const m of jwtMatches) {
  issues.push(`Token-like string found: ${m.slice(0, 20)}…`)
}

const bearerMatches = html.match(/Bearer\s+[A-Za-z0-9._~+/-]{20,}/g) || []
for (const m of bearerMatches) {
  issues.push(`Token-like string found: ${m.slice(0, 20)}…`)
}

// Token-like strings (40-64 char hex that are not known commit/hash fields, excluding pure decimal tables)
const hexMatches = html.match(/\b[0-9a-fA-F]{40,64}\b/g) || []
for (const m of hexMatches) {
  const lower = m.toLowerCase()
  // Skip pure decimal digit sequences (compiled data tables in elkjs)
  if (/^\d+$/.test(m) && !allowedHex.has(lower)) {
    continue
  }
  if (!allowedHex.has(lower)) {
    issues.push(`Token-like string found: ${m.slice(0, 20)}…`)
  }
}

if (issues.length > 0) {
  console.error('check:judge FAILED:')
  issues.forEach((i) => console.error(' •', i))
  process.exit(1)
}

console.log('check:judge passed — no absolute paths or tokens found.')
