# Stable Workflow Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make workflow nodes fully readable, keep existing nodes stable during dispatch bursts, route relationship edges clearly, and reduce dispatch-rail density.

**Architecture:** Extend the pure workflow layout module to accept measured per-node dimensions, generate provisional positions, and compute relation-aware SVG edge paths. `AgentFlow` owns the stable/pending position lifecycle and reads Vue Flow measured dimensions after node initialization. `DispatchBoard` separates tasks and activity into local tabs while `ReviewView` collapses secondary file and run information.

**Tech Stack:** Vue 3, TypeScript strict, Vue Flow, Dagre, Naive UI, Lucide Vue, Vitest.

## Global Constraints

- Do not modify backend files, API contracts, SSE events, Store event reduction, task orchestration, or replay speed.
- Keep the Windows desktop workbench structure and existing semantic design tokens.
- Node text must be fully visible; do not use fixed heights or line clamps.
- Topology bursts use a 600ms stabilization window and commit one final layout.
- All new geometry and routing logic must be pure and unit tested.
- TypeScript, ESLint, Vitest, and production build must pass.

---

### Task 1: Dimension-Aware Layout and Provisional Positions

**Files:**
- Modify: `web/src/components/workflowLayout.ts`
- Modify: `web/src/components/workflowLayout.test.ts`

**Interfaces:**
- Produces: `WorkflowNodeDimensions`, `layoutWorkflowGraph(nodes, edges, dimensions?)`, and `placeProvisionalNodes(nodes, edges, stablePositions, dimensions)`.

- [ ] Add failing tests that pass custom heights for a long coordinator and task, then assert later ranks start below their measured rectangles.
- [ ] Add failing tests that freeze existing positions, add four child tasks, and assert only new IDs receive provisional non-overlapping positions.
- [ ] Change node size lookup to prefer measured dimensions while retaining type defaults as minimums.
- [ ] Implement parent-relative provisional fan-out with deterministic IDs and collision stepping.
- [ ] Run `npm run test -- workflowLayout.test.ts` and expect all layout tests to pass.

```ts
export type WorkflowNodeDimensions = Map<string, { width: number; height: number }>

export function layoutWorkflowGraph(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  dimensions?: WorkflowNodeDimensions,
): Map<string, WorkflowPosition>
```

### Task 2: Relation-Aware Edge Router

**Files:**
- Modify: `web/src/components/workflowLayout.ts`
- Modify: `web/src/components/workflowLayout.test.ts`
- Create: `web/src/components/WorkflowEdgePath.vue`

**Interfaces:**
- Produces: `routeWorkflowEdges(nodes, edges, positions, dimensions): Map<string, RoutedWorkflowEdge>` with SVG `path` strings.
- Consumes in renderer: Vue Flow edge `data.path`, `data.relation`, and existing marker/class state.

- [ ] Add tests asserting sibling primary edges use distinct channel Y coordinates and distinct node-boundary endpoint offsets.
- [ ] Add tests asserting same-rank `handoff` uses an outside horizontal lane and upward `result` uses a left or right feedback lane outside node bounds.
- [ ] Implement deterministic source/target offset slots and orthogonal paths for primary, handoff, feedback, and evidence relations.
- [ ] Render paths with Vue Flow `BaseEdge`, retaining marker, selected, animated, and relation classes.
- [ ] Run focused tests and TypeScript checks.

```ts
export interface RoutedWorkflowEdge {
  path: string
  sourcePoint: WorkflowPosition
  targetPoint: WorkflowPosition
}
```

### Task 3: Batched AgentFlow and Natural Node Heights

**Files:**
- Modify: `web/src/components/AgentFlow.vue`

**Interfaces:**
- Consumes: measured `getNodes.value[].dimensions` from Vue Flow.
- Produces: stable node positions, provisional positions during a burst, and one committed layout after 600ms.

- [ ] Replace computed live Dagre positions with `stablePositions` and a topology watcher.
- [ ] On added IDs, keep known positions and use `placeProvisionalNodes` for new nodes; reset the 600ms timer on node, edge, or measured-dimension changes.
- [ ] After the timer, commit one dimension-aware Dagre layout, wait for the node transition, then fit the viewport once.
- [ ] Wire `@nodes-initialized` to collect real dimensions and ignore unchanged measurements.
- [ ] Remove fixed node heights, `-webkit-line-clamp`, and hidden overflow; keep stable type widths and minimum heights.
- [ ] Use `WorkflowEdgePath` for all edges and remove the duplicated zoom-button opening tag.
- [ ] Clear layout and fit timers during component unmount, then run `npm run typecheck && npm run lint`.

### Task 4: Reduce Dispatch-Rail Density

**Files:**
- Modify: `web/src/components/DispatchBoard.vue`
- Modify: `web/src/views/ReviewView.vue`

**Interfaces:**
- Keeps all current props and `select(nodeId)` event.
- Adds local-only `activeView: 'tasks' | 'activity'` and collapsed utility sections.

- [ ] Collapse the metric area into elapsed time, current/peak concurrency, completed count, and error count.
- [ ] Add a Naive UI segmented task/activity switch and render only the selected list.
- [ ] Sort missions with running and queued tasks first while preserving stable order inside each status.
- [ ] Convert changed files and recent runs into default-collapsed Naive UI collapse items with count labels.
- [ ] Verify selection, run navigation, and Diff navigation remain unchanged.

### Task 5: Verification

**Files:**
- Modify only files above when verification exposes a concrete defect.

- [ ] Run `npm run typecheck && npm run lint && npm run test && npm run build`.
- [ ] Play Demo at 1366x768 and inspect the Coordinator dispatch burst: existing nodes remain fixed, new tasks appear immediately, and one final reflow occurs.
- [ ] Verify long node labels and details show completely and measured rectangles do not overlap.
- [ ] Verify dispatch, handoff, challenge, result, and evidence paths avoid node rectangles and feedback paths stay outside the primary tree.
- [ ] Verify the left rail defaults to tasks, switches to activity, and secondary sections start collapsed.
- [ ] Verify 1536x864 and 1920x1080 have no page-level horizontal overflow or browser console errors.
