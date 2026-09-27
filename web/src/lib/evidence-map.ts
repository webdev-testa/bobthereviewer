import { MarkerType, type Node } from '@xyflow/react'
import type { EvidenceStatus } from '@/components/StatusBadge'
import { layoutNested, type LayoutLeaf, type PortPlacement, type TooltipFlowEdge } from '@/lib/nested-layout'
import type { Evidence } from '@/types/evidence'

// Leaf box, in React Flow's canvas units (not CSS pixels on the page).
const NODE_WIDTH = 240
const NODE_HEIGHT = 96

export interface MapEntry {
  key: string
  symbol: string
  path: string
  line?: number
  status: EvidenceStatus
  isTest: boolean
}

// Type aliases (not interfaces) so node data satisfies React Flow's Record<string, unknown>.
type Ports = { ports: PortPlacement[] }
export type EvidenceFlowNode = Node<{ entry: MapEntry } & Ports, 'evidence'>
export type TestsFlowNode = Node<{ targetKey: string; target: MapEntry; count: number } & Ports, 'tests'>
export type GroupFlowNode = Node<{ label: string; path: string }, 'folder' | 'file'>
export type MapNode = EvidenceFlowNode | TestsFlowNode | GroupFlowNode

type Leaf = (Omit<EvidenceFlowNode, 'position'> | Omit<TestsFlowNode, 'position'>) & Pick<LayoutLeaf, 'file' | 'folder'>

const shortName = (symbol: string) => symbol.split('.').pop() ?? symbol
const isTestSymbol = (symbol: string) => symbol.split('.').some((part) => part === 'tests' || part.startsWith('test_'))
const testsId = (targetKey: string) => `tests:${targetKey}`
const dirname = (path: string) => path.split('/').slice(0, -1).join('/')

/** What the probes on `symbol` showed, worst case first; null when no probe targets it. */
function probeStatus(evidence: Evidence, symbol: string): EvidenceStatus | null {
  const cases = evidence.probe_results.filter((p) => p.target === symbol).flatMap((p) => p.cases)
  if (!cases.length) return null
  if (cases.some((c) => c.comparison_status === 'differ')) return 'behavior_differs'
  if (cases.some((c) => c.comparison_status !== 'match')) return 'inconclusive'
  return 'same'
}

function callEdge(source: string, target: string, tooltip: string, unknown = false): TooltipFlowEdge {
  return {
    id: `${unknown ? 'unknown' : 'call'}:${source}->${target}`,
    source,
    target,
    type: 'call',
    markerEnd: { type: MarkerType.ArrowClosed },
    ariaLabel: tooltip,
    data: { tooltip, unknown },
  }
}

/** Where a "N tests call X" node sits: in the tests' file, or their shared folder when they span files. */
function testsPlacement(paths: string[]): Pick<LayoutLeaf, 'file' | 'folder'> {
  const files = [...new Set(paths)]
  if (files.length === 1) return { file: files[0] }
  const parts = files.map((f) => dirname(f).split('/'))
  return { folder: parts[0].filter((part, i) => parts.every((p) => p[i] === part)).join('/') }
}

/**
 * Callers → changed functions. Test callers of one function collapse into a single
 * "N tests call X" node unless that function is in `expandedTests`.
 */
function evidenceModel(evidence: Evidence, expandedTests: ReadonlySet<string>) {
  const entries = new Map<string, MapEntry>()
  const edges: TooltipFlowEdge[] = []
  const testsByTarget = new Map<string, string[]>()

  for (const fn of evidence.changed_functions) {
    entries.set(fn.symbol, {
      key: fn.symbol, symbol: shortName(fn.symbol), path: fn.file_path,
      status: probeStatus(evidence, fn.symbol) ?? 'changed', isTest: false,
    })
  }
  for (const fn of evidence.changed_functions) {
    for (const caller of fn.callers) {
      const isTest = isTestSymbol(caller.symbol)
      if (isTest && !expandedTests.has(fn.symbol)) {
        testsByTarget.set(fn.symbol, [...(testsByTarget.get(fn.symbol) ?? []), caller.file_path])
        continue
      }
      if (!entries.has(caller.symbol)) {
        const fallback: EvidenceStatus = caller.in_diff ? 'changed' : caller.needs_probe ? 'needs_probe' : 'outside_diff'
        entries.set(caller.symbol, {
          key: caller.symbol, symbol: shortName(caller.symbol), path: caller.file_path, line: caller.line,
          status: probeStatus(evidence, caller.symbol) ?? fallback, isTest,
        })
      }
      const via = caller.via?.length ? ` via ${caller.via.map((v) => shortName(v.symbol)).join(' → ')}` : ''
      edges.push(callEdge(caller.symbol, fn.symbol, `${caller.symbol} → ${fn.symbol}${via} · call at ${caller.file_path}:${caller.line}`))
    }
    fn.unknown_references.forEach((ref) => {
      const key = `unknown:${ref.file_path}:${ref.line}`
      entries.set(key, { key, symbol: 'Unknown reference', path: ref.file_path, line: ref.line, status: 'unknown_edge', isTest: false })
      edges.push(callEdge(key, fn.symbol, `Unknown edge: ${ref.reason} at ${ref.file_path}:${ref.line}`, true))
    })
  }
  for (const [targetKey, paths] of testsByTarget) {
    edges.push(callEdge(testsId(targetKey), targetKey, `${paths.length} test${paths.length === 1 ? '' : 's'} call ${targetKey}`))
  }

  const leaves: Leaf[] = [
    ...[...entries.values()].map((entry): Leaf => ({ id: entry.key, type: 'evidence', file: entry.path, data: { entry, ports: [] } })),
    ...[...testsByTarget].map(([targetKey, paths]): Leaf => ({
      id: testsId(targetKey), type: 'tests', ...testsPlacement(paths),
      data: { targetKey, target: entries.get(targetKey)!, count: paths.length, ports: [] },
    })),
  ]
  return { leaves, edges }
}

export async function buildEvidenceMap(evidence: Evidence, expandedTests: ReadonlySet<string>): Promise<{ nodes: MapNode[]; edges: TooltipFlowEdge[] }> {
  const { leaves, edges } = evidenceModel(evidence, expandedTests)
  const layout = await layoutNested(
    leaves.map((leaf) => ({ id: leaf.id, width: NODE_WIDTH, height: NODE_HEIGHT, file: leaf.file, folder: leaf.folder })),
    edges,
  )
  const groups: GroupFlowNode[] = layout.groups.map((group) => ({
    id: group.id,
    type: group.kind,
    position: { x: group.x, y: group.y },
    parentId: group.parentId,
    extent: group.parentId ? 'parent' : undefined,
    width: group.width,
    height: group.height,
    selectable: false,
    focusable: false,
    data: { label: group.label, path: group.path },
  }))
  const placed = leaves.map(({ file: _file, folder: _folder, ...leaf }) => {
    const spot = layout.leaves.get(leaf.id)!
    return {
      ...leaf,
      position: { x: spot.x, y: spot.y },
      parentId: spot.parentId,
      extent: spot.parentId ? ('parent' as const) : undefined,
      focusable: false,
      data: { ...leaf.data, ports: spot.ports },
    } as EvidenceFlowNode | TestsFlowNode
  })
  return { nodes: [...groups, ...placed], edges: edges.map((edge) => ({ ...edge, ...layout.handles.get(edge.id) })) }
}
