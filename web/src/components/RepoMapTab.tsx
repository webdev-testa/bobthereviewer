import { createContext, useCallback, useContext, useMemo, useRef, useState, type FocusEvent } from 'react'
import { Background, Controls, MiniMap, Panel, ReactFlow, ReactFlowProvider, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowLeftToLine, ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown, CircleAlert, FileQuestion, FlaskConical,
  Folder, FolderClosed, GitPullRequest, Import, Info, Minus, RotateCcw, Zap,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { LineSwatch, MINIMAP_FROM_NODES, PortHandles, reducedMotion, TooltipEdge, useAsyncLayout, useFlowColorMode } from '@/components/map-parts'
import type { TooltipFlowEdge } from '@/lib/nested-layout'
import {
  allFolders, buildRepoMap, CATEGORY_ORDER, collapsedId, defaultExpanded, EDGE_STYLE, fileCategories, isHot,
  type CollapsedFolderNode, type FileCategory, type LastCommit, type ModuleFlowNode, type RepoFolderFlowNode, type RepoMap,
  type RepoMapNode, type RepoMapView,
} from '@/lib/repo-map'
import { TONE_CLASSES } from '@/lib/tones'
import { cn } from '@/lib/utils'
import type { Evidence } from '@/types/evidence'

// Same vocabulary as the evidence map: blue = your change, solid = calls it, dashed = might be affected.
const CATEGORY_META: Record<FileCategory, { label: string; short: string; icon: LucideIcon; badge: string; card: string; accent: string }> = {
  changed: {
    label: 'Your change: a file this diff edits', short: 'your change', icon: GitPullRequest,
    badge: TONE_CLASSES.info, card: 'border-2 border-info bg-info-muted', accent: 'border-l-info',
  },
  impacted: {
    label: 'Calls your change: untouched, but may behave differently', short: 'calls your change', icon: Zap,
    badge: 'border-foreground/40', card: 'border-2 border-foreground/40 bg-card', accent: 'border-l-foreground/40',
  },
  imports: {
    label: 'Imports a changed file: might be affected', short: 'imports changed file', icon: Import,
    badge: 'border-dashed border-foreground/40', card: 'border-2 border-dashed border-foreground/40 bg-card', accent: 'border-l-foreground/20',
  },
  unrelated: {
    label: 'Unrelated to this change', short: 'unrelated', icon: Minus,
    badge: 'text-muted-foreground', card: 'border bg-card text-muted-foreground', accent: 'border-l-border',
  },
}

const shortSha = (sha: string) => sha.slice(0, 7)
const fileCount = (count: number) => `${count} file${count === 1 ? '' : 's'}`

function CategoryBadge({ category, short = false }: { category: FileCategory; short?: boolean }) {
  const { icon: Icon, badge, label, short: shortLabel } = CATEGORY_META[category]
  return <Badge variant="outline" className={badge}><Icon aria-hidden="true" />{short ? shortLabel : label}</Badge>
}

function TestBadge() {
  return <Badge variant="outline" className="text-muted-foreground"><FlaskConical aria-hidden="true" />test</Badge>
}

/** "2 your change · 1 calls your change" for a folder; unrelated files count only in the folder total. */
function categoryCounts(counts: Record<FileCategory, number>) {
  const parts = CATEGORY_ORDER.filter((c) => c !== 'unrelated' && counts[c]).map((c) => `${counts[c]} ${CATEGORY_META[c].short}`)
  return parts.join(' · ') || 'nothing changed or affected'
}

const RepoMapActions = createContext<{ toggle: (folder: string, open: boolean) => void; showEvidence: () => void } | null>(null)

function useActions() {
  const actions = useContext(RepoMapActions)
  if (!actions) throw new Error('Repo map nodes render only inside the repo map.')
  return actions
}

function CommitInfo({ commit, about }: { commit: LastCommit | null; about: string }) {
  if (!commit) return <span className="min-w-0 flex-1 truncate">No commit found</span>
  return (
    <>
      <span className="min-w-0 flex-1 truncate">{shortSha(commit.sha)} · {commit.date}{commit.pr ? ` · PR #${commit.pr}` : ''}</span>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-xs" className="nodrag" aria-label={`Latest change in ${about}: ${commit.subject}`}>
            <Info aria-hidden="true" />
          </Button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">{commit.subject}</TooltipContent>
      </Tooltip>
    </>
  )
}

function FolderToggle({ folder, label, open }: { folder: string; label: string; open: boolean }) {
  const { toggle } = useActions()
  const Icon = open ? ChevronDown : ChevronRight
  return (
    <Button
      variant="ghost" size="icon-xs" className="nodrag" aria-expanded={open}
      aria-label={`${open ? 'Collapse' : 'Expand'} folder ${label}`}
      onClick={(event) => { event.stopPropagation(); toggle(folder, !open) }}
    >
      <Icon aria-hidden="true" />
    </Button>
  )
}

function ModuleNode({ data }: NodeProps<ModuleFlowNode>) {
  const { module, category, isTest } = data
  const { showEvidence } = useActions()
  return (
    <Card className={cn('h-24 w-70 gap-1 p-2 shadow-sm', CATEGORY_META[category].card)}>
      <PortHandles ports={data.ports} />
      <span className="truncate font-mono text-xs font-semibold text-foreground">{module.path.split('/').pop()}</span>
      <div className="flex items-center gap-1">
        <CategoryBadge category={category} short />
        {isTest ? <TestBadge /> : null}
      </div>
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <CommitInfo commit={module.last_commit} about={module.path} />
        {isHot(category) ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-xs" className="nodrag" aria-label={`Show ${module.path} in the evidence map`} onClick={showEvidence}>
                <ArrowLeftToLine aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Show in the evidence map</TooltipContent>
          </Tooltip>
        ) : null}
      </div>
    </Card>
  )
}

function CollapsedNode({ data }: NodeProps<CollapsedFolderNode>) {
  const { label, summary } = data
  return (
    <Card className={cn('h-24 w-70 cursor-pointer gap-1 border-l-4 p-2 shadow-sm', CATEGORY_META[summary.strongest].accent)}>
      <PortHandles ports={data.ports} />
      <div className="flex items-center gap-1 text-xs">
        <FolderToggle folder={summary.path} label={label} open={false} />
        <FolderClosed aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-mono font-semibold">{label}/</span>
        <span className="shrink-0 text-muted-foreground">{fileCount(summary.fileCount)}</span>
      </div>
      <p className="truncate text-xs">{categoryCounts(summary.counts)}</p>
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <CommitInfo commit={summary.latest} about={summary.path} />
      </div>
    </Card>
  )
}

function RepoFolderGroup({ data }: NodeProps<RepoFolderFlowNode>) {
  const { label, summary } = data
  return (
    <div className="size-full rounded-lg bg-muted/60" aria-label={`Folder ${summary.path}`}>
      <div className="flex items-center gap-1 px-2 pt-1.5 text-xs text-muted-foreground">
        <FolderToggle folder={summary.path} label={label} open />
        <Folder aria-hidden="true" className="size-3.5 shrink-0" />
        <span className="shrink-0 font-medium text-foreground">{label}</span>
        <span className="shrink-0">· {fileCount(summary.fileCount)} ·</span>
        <CommitInfo commit={summary.latest} about={summary.path} />
      </div>
    </div>
  )
}

const nodeTypes = { module: ModuleNode, collapsed: CollapsedNode, repoFolder: RepoFolderGroup }
const edgeTypes = { call: TooltipEdge }

function LegendSheet() {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm"><Info aria-hidden="true" />Legend</Button>
      </SheetTrigger>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>How to read the repo map</SheetTitle>
          <SheetDescription>
            Every source file in the repository, grouped by folder. Arrows point from a file to the file it imports.
            Folders open only down to what this change touches; open or close any folder with its arrow.
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-6">
          <section className="space-y-2">
            <h3 className="text-sm font-medium">Box: what the file is to this change</h3>
            <ul className="space-y-2">
              {CATEGORY_ORDER.map((category) => <li key={category}><CategoryBadge category={category} /></li>)}
              <li className="flex items-center gap-2 text-sm text-muted-foreground"><TestBadge />part of the test suite</li>
            </ul>
          </section>
          <section className="space-y-2">
            <h3 className="text-sm font-medium">Arrows: imports</h3>
            <ul className="space-y-2">
              <LineSwatch label="Between changed files and their callers" lineStyle={EDGE_STYLE.strong} />
              <LineSwatch label="Touching a file that imports a changed one" lineStyle={EDGE_STYLE.medium} />
              <LineSwatch label="Other imports" lineStyle={EDGE_STYLE.weak} />
            </ul>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  )
}

/** The boxes to fit on load: the toggled folder, else the changed and impacted files. */
function focusIds(nodes: RepoMapNode[], toggled: string | null): string[] {
  const folder = toggled === null ? [] : nodes.filter((n) => n.id === collapsedId(toggled) || n.id === `folder:${toggled}`)
  if (folder.length) return folder.map((n) => n.id)
  return nodes
    .filter((n) => (n.type === 'module' && isHot(n.data.category)) || (n.type === 'collapsed' && n.data.summary.counts.changed + n.data.summary.counts.impacted > 0))
    .map((n) => n.id)
}

/** Node positions ease into a new layout only right after an expand or collapse, never while dragging. */
function useLayoutTransition() {
  const [animating, setAnimating] = useState(false)
  const timer = useRef<number>(undefined)
  const pulse = useCallback(() => {
    setAnimating(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setAnimating(false), 400)
  }, [])
  return { animating, pulse }
}

/** Edges of the hovered or focused box stay; the rest fade, so one file's imports read at a glance. */
function useEdgeFocus(edges: TooltipFlowEdge[]) {
  const [active, setActive] = useState<string | null>(null)
  const shown = useMemo(() => {
    if (!active) return edges
    return edges.map((e) =>
      e.source === active || e.target === active ? { ...e, zIndex: 2, style: { ...e.style, opacity: 1 } } : { ...e, style: { ...e.style, opacity: 0.08 } },
    )
  }, [edges, active])
  const fromNode = (node: Node) => setActive(node.type === 'repoFolder' ? null : node.id)
  const fromFocus = (event: FocusEvent) => {
    const id = (event.target as Element).closest('.react-flow__node')?.getAttribute('data-id') ?? null
    setActive(id && (id.startsWith('module:') || id.startsWith('collapsed:')) ? id : null)
  }
  return { shown, fromNode, fromFocus, clear: () => setActive(null) }
}

interface ViewControls {
  view: RepoMapView
  expandAll: () => void
  collapseAll: () => void
  setFocusOnly: (on: boolean) => void
  reset: () => void
}

function Toolbar({ controls }: { controls: ViewControls }) {
  return (
    <Panel position="top-right" className="flex flex-wrap items-center justify-end gap-2">
      <div className="flex items-center gap-2 rounded-md border bg-card px-2 py-1">
        <Switch id="repo-map-focus-only" checked={controls.view.focusOnly} onCheckedChange={controls.setFocusOnly} />
        <Label htmlFor="repo-map-focus-only" className="text-sm font-normal">Affected files only</Label>
      </div>
      <Button variant="outline" size="sm" onClick={controls.expandAll}><ChevronsUpDown aria-hidden="true" />Expand all</Button>
      <Button variant="outline" size="sm" onClick={controls.collapseAll}><ChevronsDownUp aria-hidden="true" />Collapse all</Button>
      <Button variant="outline" size="sm" onClick={controls.reset}><RotateCcw aria-hidden="true" />Reset</Button>
      <LegendSheet />
    </Panel>
  )
}

function useViewControls(map: RepoMap, categories: Map<string, FileCategory>, pulse: () => void) {
  const initial = useMemo(() => defaultExpanded(categories), [categories])
  const [view, setView] = useState<RepoMapView>({ expanded: initial, focusOnly: false })
  const toggled = useRef<string | null>(null)
  const change = useCallback((next: (view: RepoMapView) => RepoMapView, folder: string | null = null) => {
    toggled.current = folder
    pulse()
    setView(next)
  }, [pulse])
  const toggle = useCallback((folder: string, open: boolean) => change((v) => {
    const expanded = new Set(v.expanded)
    if (open) expanded.add(folder)
    else expanded.delete(folder)
    return { ...v, expanded }
  }, folder), [change])
  const controls: ViewControls = {
    view,
    expandAll: () => change((v) => ({ ...v, expanded: allFolders(map) })),
    collapseAll: () => change((v) => ({ ...v, expanded: new Set() })),
    setFocusOnly: (focusOnly) => change((v) => ({ ...v, focusOnly })),
    reset: () => change(() => ({ expanded: new Set(initial), focusOnly: false })),
  }
  return { controls, toggle, toggled }
}

function Canvas({ map, categories, controls, toggled, animating }: {
  map: RepoMap; categories: Map<string, FileCategory>; controls: ViewControls; toggled: { current: string | null }; animating: boolean
}) {
  const colorMode = useFlowColorMode()
  const { toggle, showEvidence } = useActions()
  const { nodes, edges, onNodesChange, onEdgesChange, error } = useAsyncLayout<RepoMapNode, TooltipFlowEdge>(
    () => buildRepoMap(map, categories, controls.view, reducedMotion()),
    [map, categories, controls.view],
    (laidOut) => focusIds(laidOut, toggled.current),
  )
  const focus = useEdgeFocus(edges)
  if (error) {
    return (
      <Alert variant="destructive" className="m-4 w-auto">
        <CircleAlert aria-hidden="true" />
        <AlertTitle>The repo map could not be laid out</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }
  return (
    <ReactFlow
      colorMode={colorMode}
      className={cn(animating && 'flow-animate')}
      nodes={nodes}
      edges={focus.shown}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={(_, node) => {
        if (node.type === 'collapsed') toggle(node.data.summary.path, true)
        else if (node.type === 'module' && isHot(node.data.category)) showEvidence()
      }}
      onNodeMouseEnter={(_, node) => focus.fromNode(node)}
      onNodeMouseLeave={focus.clear}
      onFocus={focus.fromFocus}
      onBlur={focus.clear}
      nodesConnectable={false}
      minZoom={0.05}
      defaultEdgeOptions={{ zIndex: 1 }}
    >
      <Background />
      <Controls showInteractive={false} />
      {nodes.length >= MINIMAP_FROM_NODES ? <MiniMap className="hidden sm:block" pannable zoomable ariaLabel="Repo map overview" /> : null}
      <Toolbar controls={controls} />
    </ReactFlow>
  )
}

function RepoMapBody({ evidence, map, onShowEvidence }: { evidence: Evidence; map: RepoMap; onShowEvidence: () => void }) {
  const categories = useMemo(() => fileCategories(map, evidence), [map, evidence])
  const { animating, pulse } = useLayoutTransition()
  const { controls, toggle, toggled } = useViewControls(map, categories, pulse)
  const actions = useMemo(() => ({ toggle, showEvidence: onShowEvidence }), [toggle, onShowEvidence])
  return (
    <RepoMapActions.Provider value={actions}>
      <div role="group" aria-labelledby="repo-map-heading" className="h-128 w-full overflow-hidden rounded-md border bg-background">
        <Canvas map={map} categories={categories} controls={controls} toggled={toggled} animating={animating} />
      </div>
    </RepoMapActions.Provider>
  )
}

function UnknownImports({ map }: { map: RepoMap }) {
  if (!map.unknowns.length) return null
  return (
    <section aria-label="Unknown imports" className="space-y-2">
      <h3 className="font-medium">Unknown imports ({map.unknowns.length})</h3>
      {map.unknowns.map((u) => (
        <Alert key={`${u.path}:${u.line}:${u.expression}`} className={TONE_CLASSES.warning}>
          <AlertTitle className="font-mono break-all">{u.expression} at {u.path}:{u.line}</AlertTitle>
          <AlertDescription>{u.reason}; this import is not drawn, and is not assumed to be absent.</AlertDescription>
        </Alert>
      ))}
    </section>
  )
}

interface Props {
  evidence: Evidence
  /** null when the run has no repo map. */
  map: RepoMap | null
  onShowEvidence: () => void
}

export function RepoMapTab({ evidence, map, onShowEvidence }: Props) {
  if (!map) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon"><FileQuestion aria-hidden="true" /></EmptyMedia>
          <EmptyTitle>No repo map for this review</EmptyTitle>
          <EmptyDescription>
            Reviews save a repo map from <code>bobreviewer run</code>; run one on this change, or build one with <code>bobreviewer map</code>.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle><h2 id="repo-map-heading" className="text-lg font-semibold">Repo map</h2></CardTitle>
        <CardDescription>
          {map.modules.length} files and {map.edges.length} imports at <code>{shortSha(map.sha)}</code>. Hover a file to follow its imports.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ReactFlowProvider>
          <RepoMapBody key={`${map.sha}:${evidence.run_id}`} evidence={evidence} map={map} onShowEvidence={onShowEvidence} />
        </ReactFlowProvider>
        <UnknownImports map={map} />
        {map.limits.length ? (
          <ul className="max-w-prose list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {map.limits.map((limit) => <li key={limit}>{limit}</li>)}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  )
}
