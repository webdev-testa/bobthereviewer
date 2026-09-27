import { useCallback, useEffect } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import ELK from 'elkjs/lib/elk.bundled.js'
import type { ChangedFunction } from '@/types/evidence'
import { buildGraph, type NodeData } from '@/lib/build-graph'
import { cn } from '@/lib/utils'

const elk = new ELK()

type FlowNode = Node<NodeData>

const KIND_STYLES: Record<NodeData['kind'], string> = {
  changed:          'border-info bg-info-muted text-info',
  'caller-outside': 'border-warning bg-warning-muted text-warning',
  'caller-inside':  'border-border bg-muted/40 text-foreground',
  unknown:          'border-neutral bg-neutral-muted text-neutral border-dashed',
}

function CustomNode({ data }: NodeProps<FlowNode>) {
  return (
    <div className={cn('rounded-md border px-3 py-1.5 text-xs min-w-[120px] max-w-[200px]', KIND_STYLES[data.kind])}>
      <div className="font-mono font-medium truncate">{data.label}</div>
      <div className="text-[10px] opacity-70 truncate">{data.sublabel}</div>
      {data.kind === 'caller-outside' && (
        <div className="text-[10px] font-medium mt-0.5">Outside diff</div>
      )}
      {data.kind === 'unknown' && (
        <div className="text-[10px] font-medium mt-0.5">Unknown edge</div>
      )}
    </div>
  )
}

const NODE_TYPES = { default: CustomNode }

async function applyElkLayout(nodes: FlowNode[], edges: Edge[]): Promise<FlowNode[]> {
  const graph = {
    id: 'root',
    layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.spacing.nodeNode': '40' },
    children: nodes.map((n) => ({ id: n.id, width: 200, height: 56 })),
    edges: edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  }
  const laid = await elk.layout(graph)
  return nodes.map((n) => {
    const el = laid.children?.find((c) => c.id === n.id)
    return el ? { ...n, position: { x: el.x ?? 0, y: el.y ?? 0 } } : n
  })
}

interface Props { fn: ChangedFunction }

export function CallerMap({ fn }: Props) {
  const { nodes: initNodes, edges: initEdges } = buildGraph(fn)
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(initNodes)
  const [edges, , onEdgesChange] = useEdgesState(initEdges)

  const layout = useCallback(async () => {
    const laid = await applyElkLayout(nodes, edges)
    setNodes(laid)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void layout() }, [layout])

  return (
    <div className="h-56 w-full rounded-md border border-border overflow-hidden bg-card">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={NODE_TYPES}
        fitView
        attributionPosition="bottom-right"
      >
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  )
}
