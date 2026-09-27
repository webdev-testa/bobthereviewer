import { createContext, useContext, useMemo, useState } from 'react'
import { Background, Controls, MiniMap, Panel, ReactFlow, ReactFlowProvider, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { ChevronDown, ChevronRight, CircleAlert, FileCode, FlaskConical, Folder, FolderClosed, Info, RotateCcw } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import {
  LineSwatch, MINIMAP_FROM_NODES, PortHandles, TooltipEdge, UNKNOWN_EDGE_DASH, useAsyncLayout, useFlowColorMode,
} from '@/components/map-parts'
import { StatusBadge, STATUS_META, type EvidenceStatus } from '@/components/StatusBadge'
import {
  buildEvidenceMap, type CollapsedFlowNode, type EvidenceFlowNode, type GroupFlowNode, type MapEntry, type MapNode, type MapRole,
  type TestsFlowNode,
} from '@/lib/evidence-map'
import type { TooltipFlowEdge } from '@/lib/nested-layout'
import type { Tone } from '@/lib/tones'
import { cn } from '@/lib/utils'
import type { Evidence } from '@/types/evidence'

// Two questions, two channels: the box color says what running the code showed,
// the outline says what the code is. Neither ever encodes the other.
const FILL: Record<Tone, string> = {
  danger: 'bg-danger-muted', warning: 'bg-warning-muted', success: 'bg-success-muted', neutral: 'bg-card', info: 'bg-card',
}
const OUTLINE: Record<MapRole, string> = {
  changed: 'border-info', affected: 'border-foreground/25', possible: 'border-dashed border-foreground/40',
}
const ROLE_LABEL: Record<MapRole, string> = {
  changed: 'Your change', affected: 'Calls your change', possible: 'Might call your change',
}

function RoleTag({ role }: { role: MapRole }) {
  return <span className={cn('truncate text-xs font-medium', role === 'changed' ? 'text-info' : 'text-muted-foreground')}>{ROLE_LABEL[role]}</span>
}

function EvidenceNodeCard({ data: { entry, ports } }: NodeProps<EvidenceFlowNode>) {
  return (
    <Card className={cn('h-24 w-60 cursor-pointer gap-1 border-2 p-2 shadow-sm', FILL[STATUS_META[entry.status].tone], OUTLINE[entry.role])}>
      <PortHandles ports={ports} />
      <span className="truncate font-mono text-sm font-semibold text-foreground">{entry.symbol}</span>
      <span className="truncate text-xs text-muted-foreground">
        {entry.path}{entry.line ? `:${entry.line}` : ''}{entry.isTest ? ' · test' : ''}
      </span>
      <span className="flex min-w-0 items-center gap-2">
        <StatusBadge status={entry.status} className="shrink-0" />
        <RoleTag role={entry.role} />
      </span>
    </Card>
  )
}

function TestsNodeCard({ data }: NodeProps<TestsFlowNode>) {
  return (
    <Card className={cn('h-24 w-60 cursor-pointer gap-1 border-2 bg-card p-2 shadow-sm', OUTLINE.affected)}>
      <PortHandles ports={data.ports} />
      <span className="flex items-center gap-1 text-sm font-semibold text-foreground">
        <FlaskConical aria-hidden="true" className="size-4" />
        {data.count} test{data.count === 1 ? '' : 's'} call <span className="truncate font-mono">{data.target.symbol}</span>
      </span>
      <span className="text-xs text-muted-foreground">Select to show them</span>
    </Card>
  )
}

function FileGroup({ data }: NodeProps<GroupFlowNode>) {
  return (
    <div className="size-full rounded-md border bg-card/80" aria-label={`File ${data.path}`}>
      <span className="flex items-center gap-2 px-3 pt-2 text-xs font-medium">
        <FileCode aria-hidden="true" className="size-3.5 text-muted-foreground" />
        <span className="truncate">{data.label}</span>
      </span>
    </div>
  )
}

// Folder boxes are React Flow nodes, so the toggle reaches them through context, not props.
const ToggleFolder = createContext<(path: string) => void>(() => {})

function FolderToggle({ path, label, open }: { path: string; label: string; open: boolean }) {
  const toggle = useContext(ToggleFolder)
  const Chevron = open ? ChevronDown : ChevronRight
  return (
    <Button
      variant="ghost" size="icon-xs" className="nodrag" aria-expanded={open}
      aria-label={`${open ? 'Collapse' : 'Expand'} folder ${label}`}
      onClick={(event) => { event.stopPropagation(); toggle(path) }}
    >
      <Chevron aria-hidden="true" />
    </Button>
  )
}

function FolderGroup({ data }: NodeProps<GroupFlowNode>) {
  return (
    <div className="size-full rounded-lg bg-muted/60" aria-label={`Folder ${data.path}`}>
      <span className="flex items-center gap-1 px-2 pt-1.5 text-xs font-medium text-muted-foreground">
        <FolderToggle path={data.path} label={data.label} open />
        <Folder aria-hidden="true" className="size-3.5" />
        {data.label}
      </span>
    </div>
  )
}

function CollapsedCard({ data }: NodeProps<CollapsedFlowNode>) {
  return (
    <Card className={cn('h-24 w-60 cursor-pointer gap-1 border-2 p-2 shadow-sm', FILL[STATUS_META[data.status].tone], OUTLINE.affected)}>
      <PortHandles ports={data.ports} />
      <span className="flex items-center gap-1 text-sm font-semibold text-foreground">
        <FolderToggle path={data.path} label={data.label} open={false} />
        <FolderClosed aria-hidden="true" className="size-4 shrink-0" />
        <span className="truncate">{data.label}</span>
      </span>
      <span className="truncate text-xs text-muted-foreground">{data.count} function{data.count === 1 ? '' : 's'} inside</span>
      <StatusBadge status={data.status} className="w-fit" />
    </Card>
  )
}

const nodeTypes = {
  evidence: EvidenceNodeCard,
  tests: TestsNodeCard,
  collapsed: CollapsedCard,
  folder: FolderGroup,
  file: FileGroup,
}
const edgeTypes = { call: TooltipEdge }

function SampleBox({ role, label }: { role: MapRole; label: string }) {
  return (
    <li className="flex items-center gap-3 text-sm">
      <span aria-hidden="true" className={cn('h-6 w-10 shrink-0 rounded-md border-2 bg-card', OUTLINE[role])} />
      {label}
    </li>
  )
}

function LegendGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium">{title}</h3>
      <ul className="space-y-2">{children}</ul>
    </section>
  )
}

const COLOR_MEANING: [EvidenceStatus, string][] = [
  ['behavior_differs', 'Same input, different output before and after. You decide if that was intended.'],
  ['same', 'Every tried input gave the same output.'],
  ['inconclusive', 'The probe could not run on one side (for example, an import broke).'],
  ['needs_probe', 'Not checked yet, and worth checking: nobody reviewing the diff would look here.'],
  ['not_run', 'Not checked, and the analysis did not flag it (for example, only tests call it, or it is in the diff).'],
]

function LegendSheet() {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm"><Info aria-hidden="true" />Legend</Button>
      </SheetTrigger>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>How to read the map</SheetTitle>
          <SheetDescription>
            Each box is a function. Arrows point from a function to the code it calls, so your change sits on the
            right and the code that depends on it on the left.
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-6">
          <p className="rounded-md bg-muted p-3 text-sm">
            <span className="font-medium">What's a probe?</span> A small file naming one function and a few example
            inputs. The tool runs those inputs on the old and the new code and compares the outputs. You (or Bob)
            write probes for the callers worth checking.
          </p>
          <LegendGroup title="Outline: what the code is">
            <SampleBox role="changed" label="Your change: a function this diff edits" />
            <SampleBox role="affected" label="Calls your change: untouched, but may now behave differently" />
            <SampleBox role="possible" label="Might call your change: a dynamic call the tool can't follow" />
          </LegendGroup>
          <LegendGroup title="Color: what running it showed">
            {COLOR_MEANING.map(([status, meaning]) => (
              <li key={status} className="space-y-1 text-sm">
                <StatusBadge status={status} />
                <p className="text-muted-foreground">{meaning}</p>
              </li>
            ))}
          </LegendGroup>
          <LegendGroup title="Lines">
            <LineSwatch label="Calls: the tool read this call in the code" />
            <LineSwatch label="Might call: decided at runtime, so it can't be confirmed" dash={UNKNOWN_EDGE_DASH} />
          </LegendGroup>
        </div>
      </SheetContent>
    </Sheet>
  )
}

const show = (value: unknown) => JSON.stringify(value)

function DetailsSheet({ evidence, entry, onClose }: { evidence: Evidence; entry: MapEntry | undefined; onClose: () => void }) {
  const cases = entry ? evidence.probe_results.filter((p) => p.target === entry.key).flatMap((p) => p.cases) : []
  return (
    <Sheet open={!!entry} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-lg">
        {entry ? (
          <>
            <SheetHeader>
              <SheetTitle className="pr-8 font-mono break-all">{entry.key.startsWith('unknown:') ? entry.symbol : entry.key}</SheetTitle>
              <SheetDescription className="break-all">
                {entry.path}{entry.line ? `:${entry.line}` : ''}{entry.isTest ? ' · test code' : ''}
              </SheetDescription>
              <span className="flex flex-wrap items-center gap-2">
                <StatusBadge status={entry.status} />
                <RoleTag role={entry.role} />
              </span>
            </SheetHeader>
            <section aria-label="Probe results" className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 pb-4">
              <h3 className="font-medium">Probe results</h3>
              {cases.length ? cases.map((c) => (
                <div key={c.id} className="space-y-2 rounded-md border p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <code className="font-semibold">{c.id}</code>
                    <span className="text-muted-foreground">{c.comparison_status ?? c.execution_status}</span>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <pre className="overflow-x-auto rounded-md bg-muted p-2 font-mono whitespace-pre-wrap break-all">before: {show(c.base_output)}</pre>
                    <pre className="overflow-x-auto rounded-md bg-muted p-2 font-mono whitespace-pre-wrap break-all">after: {show(c.head_output)}</pre>
                  </div>
                  {c.inconclusive_reason ? <p className="text-muted-foreground">{c.inconclusive_reason}</p> : null}
                </div>
              )) : <p className="text-sm text-muted-foreground">No probe targets this function.</p>}
            </section>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}

function Canvas({ evidence }: { evidence: Evidence }) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())
  const [selected, setSelected] = useState<MapEntry>()
  const { nodes, edges, onNodesChange, onEdgesChange, error, reset } = useAsyncLayout<MapNode, TooltipFlowEdge>(
    () => buildEvidenceMap(evidence, expanded, collapsed),
    [evidence, expanded, collapsed],
  )
  const colorMode = useFlowColorMode()
  const leafCount = useMemo(() => nodes.filter((n) => n.type === 'evidence' || n.type === 'tests').length, [nodes])

  if (error) {
    return (
      <Alert variant="destructive" className="m-4 w-auto">
        <CircleAlert aria-hidden="true" />
        <AlertTitle>The map could not be laid out</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }

  const toggleIn = (key: string) => (current: ReadonlySet<string>) => {
    const next = new Set(current)
    if (!next.delete(key)) next.add(key)
    return next
  }
  const toggleFolder = (path: string) => setCollapsed(toggleIn(path))

  return (
    <ToggleFolder.Provider value={toggleFolder}>
      <ReactFlow
        colorMode={colorMode}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => {
          if (node.type === 'tests') setExpanded(toggleIn(node.data.targetKey))
          else if (node.type === 'collapsed') toggleFolder(node.data.path)
          else if (node.type === 'evidence') setSelected(node.data.entry)
        }}
        nodesConnectable={false}
        minZoom={0.1}
        defaultEdgeOptions={{ style: { strokeWidth: 2 }, zIndex: 1 }}
      >
        <Background />
        <Controls showInteractive={false} />
        {leafCount >= MINIMAP_FROM_NODES ? <MiniMap className="hidden sm:block" pannable zoomable ariaLabel="Map overview" /> : null}
        <Panel position="top-right" className="flex gap-2">
          {collapsed.size ? (
            <Button variant="outline" size="sm" onClick={() => setCollapsed(new Set())}>
              <Folder aria-hidden="true" />Expand all
            </Button>
          ) : null}
          {expanded.size ? (
            <Button variant="outline" size="sm" onClick={() => setExpanded(new Set())}>
              <FlaskConical aria-hidden="true" />Group test callers
            </Button>
          ) : null}
          <Button variant="outline" size="sm" onClick={reset}>
            <RotateCcw aria-hidden="true" />Reset layout
          </Button>
          <LegendSheet />
        </Panel>
      </ReactFlow>
      <DetailsSheet evidence={evidence} entry={selected} onClose={() => setSelected(undefined)} />
    </ToggleFolder.Provider>
  )
}

export function EvidenceMap({ evidence }: { evidence: Evidence }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle><h2 className="text-lg font-semibold">Evidence map</h2></CardTitle>
        <CardDescription>What this change can reach, and what running it showed. Select a box for details.</CardDescription>
      </CardHeader>
      <CardContent>
        {evidence.changed_functions.length ? (
          <div className="h-96 w-full overflow-hidden rounded-md border bg-background sm:h-128">
            <ReactFlowProvider>
              <Canvas evidence={evidence} />
            </ReactFlowProvider>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No changed functions to map.</p>
        )}
      </CardContent>
    </Card>
  )
}
