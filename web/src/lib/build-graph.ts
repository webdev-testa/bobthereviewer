/**
 * Converts a ChangedFunction into React Flow nodes + edges.
 * ELK layout is applied separately via useLayoutedElements.
 */
import type { Node, Edge } from '@xyflow/react'
import type { ChangedFunction } from '@/types/evidence'

export type NodeData = {
  label: string
  sublabel: string
  kind: 'changed' | 'caller-outside' | 'caller-inside' | 'unknown'
}

export function buildGraph(fn: ChangedFunction): { nodes: Node<NodeData>[]; edges: Edge[] } {
  const nodes: Node<NodeData>[] = []
  const edges: Edge[] = []

  nodes.push({
    id: 'root',
    type: 'default',
    position: { x: 0, y: 0 },
    data: { label: fn.symbol.split('.').pop() ?? fn.symbol, sublabel: fn.file_path, kind: 'changed' },
  })

  fn.callers.forEach((c, i) => {
    const id = `caller-${i}`
    nodes.push({
      id,
      type: 'default',
      position: { x: 0, y: 0 },
      data: {
        label: c.symbol.split('.').pop() ?? c.symbol,
        sublabel: `${c.file_path}:${c.line}`,
        kind: c.in_diff ? 'caller-inside' : 'caller-outside',
      },
    })
    edges.push({ id: `e-${i}`, source: id, target: 'root', type: 'smoothstep' })
  })

  fn.unknown_references.forEach((r, i) => {
    const id = `unknown-${i}`
    nodes.push({
      id,
      type: 'default',
      position: { x: 0, y: 0 },
      data: { label: 'Unknown edge', sublabel: `${r.file_path}:${r.line}`, kind: 'unknown' },
    })
    edges.push({ id: `eu-${i}`, source: id, target: 'root', type: 'smoothstep', style: { strokeDasharray: '4 2' } })
  })

  return { nodes, edges }
}
