import fs from 'node:fs'
import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Judge build — single inlined HTML with selectable PR reviews
export default defineConfig(() => {
  const judgePrsEnv = process.env.JUDGE_PRS
  if (!judgePrsEnv) {
    throw new Error(
      'JUDGE_PRS environment variable is missing. Set JUDGE_PRS to a folder containing index.json and PR artifact subfolders.'
    )
  }

  const prsDir = path.resolve(process.cwd(), judgePrsEnv)
  if (!fs.existsSync(prsDir)) {
    throw new Error(`JUDGE_PRS folder does not exist: ${prsDir}`)
  }

  const indexPath = path.join(prsDir, 'index.json')
  if (!fs.existsSync(indexPath)) {
    throw new Error(`JUDGE_PRS index.json not found in: ${prsDir}`)
  }

  let indexEntries: any[]
  try {
    indexEntries = JSON.parse(fs.readFileSync(indexPath, 'utf-8'))
  } catch (err) {
    throw new Error(`Failed to parse ${indexPath}: ${err}`)
  }

  if (!Array.isArray(indexEntries) || indexEntries.length === 0) {
    throw new Error(`index.json in ${prsDir} must contain a non-empty array of PR entries.`)
  }

  const prsData = indexEntries.map((entry) => {
    if (!entry.id || typeof entry.id !== 'string') {
      throw new Error(`PR entry is missing 'id': ${JSON.stringify(entry)}`)
    }

    const entryDir = path.join(prsDir, entry.id)
    const evidencePath = path.join(entryDir, 'evidence.json')
    if (!fs.existsSync(evidencePath)) {
      throw new Error(`PR '${entry.id}' is missing required evidence.json: ${evidencePath}`)
    }

    let evidence: any
    try {
      evidence = JSON.parse(fs.readFileSync(evidencePath, 'utf-8'))
    } catch (err) {
      throw new Error(`Failed to parse evidence for '${entry.id}': ${err}`)
    }

    if (evidence.fixture === true) {
      throw new Error(
        `PR '${entry.id}' contains fixture evidence ("fixture": true). The judge page requires real review evidence.`
      )
    }

    let repoMap = null
    const repoMapPath = path.join(entryDir, 'repo_map.json')
    if (fs.existsSync(repoMapPath)) {
      try {
        repoMap = JSON.parse(fs.readFileSync(repoMapPath, 'utf-8'))
      } catch (err) {
        console.warn(`Warning: failed to parse repo_map.json for '${entry.id}': ${err}`)
      }
    }

    return {
      id: entry.id,
      pr: entry.pr ?? 0,
      title: entry.title ?? entry.id,
      label: entry.label ?? entry.title ?? entry.id,
      pr_url: entry.pr_url ?? '',
      run_url: entry.run_url ?? '',
      evidence,
      repoMap,
    }
  })

  return {
    plugins: [react(), tailwindcss(), viteSingleFile()],
    resolve: {
      alias: {
        '@': `${import.meta.dirname}/src`,
      },
    },
    define: {
      __JUDGE_MODE__: JSON.stringify(true),
      __JUDGE_PRS__: JSON.stringify(prsData),
    },
    build: {
      outDir: 'dist-judge',
      emptyOutDir: true,
    },
  }
})
