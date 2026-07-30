# Windows Review Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Vue frontend as a coherent Windows desktop review workbench with a live, smoothly reflowing workflow graph.

**Architecture:** Keep the existing Vue, Pinia, Naive UI, Vue Flow, and API contracts. Extract the pure Dagre layout calculation from `AgentFlow`, then restructure the review page around a full-height central graph with collapsible auxiliary rails and a bottom event drawer. Apply one shared visual language to Review, Diff, and Benchmark without introducing a new framework.

**Tech Stack:** Vue 3, TypeScript strict, Pinia, Vue Flow, `@dagrejs/dagre`, Naive UI, Lucide Vue, ECharts, Tailwind CSS tokens, Vitest.

## Global Constraints

- Do not modify backend files, backend processes, API contracts, SSE events, task orchestration, or replay business logic.
- Target Windows desktop browser viewports at 1366x768, 1536x864, and 1920x1080.
- Do not add mobile, tablet, macOS, or Linux specific layouts.
- Use existing CSS variables for colors, radii, spacing, and typography; do not add raw hex colors or inline styles.
- Keep TypeScript strict and do not introduce `any`.
- Use existing Naive UI controls and Lucide icons for actions.
- Loading uses skeletons, errors use existing toasts, empty lists retain actionable empty copy, and all clickable controls have hover, active, and focus-visible feedback.

---

### Task 1: Pure Live Graph Layout

**Files:**
- Create: `web/src/components/workflowLayout.ts`
- Create: `web/src/components/workflowLayout.test.ts`

**Interfaces:**
- Consumes: `WorkflowNode[]`, `WorkflowEdge[]`, and the existing `WorkflowKind` union.
- Produces: `layoutWorkflowGraph(nodes, edges): Map<string, { x: number; y: number }>` and exported `WORKFLOW_NODE_SIZES`.

- [ ] **Step 1: Write layout tests**

Cover empty input, a vertical chain, three parallel children, a multi-parent verifier, an isolated node, and deterministic output when input arrays are reversed. Assert unique non-overlapping rectangles and increasing `y` values along the main chain.

```ts
const result = layoutWorkflowGraph(nodes, edges)
expect(result.get('input')?.y).toBeLessThan(result.get('coordinator')?.y ?? 0)
expect(rectanglesOverlap(result, nodes)).toBe(false)
expect([...layoutWorkflowGraph([...nodes].reverse(), [...edges].reverse())]).toEqual([...result])
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `npm run test -- workflowLayout.test.ts`

Expected: FAIL because `workflowLayout.ts` does not exist.

- [ ] **Step 3: Implement deterministic Dagre layout**

Sort nodes and valid edges by stable IDs before inserting them into Dagre. Configure `rankdir: 'TB'`, fixed rank/node separation, and shared node dimensions. Convert Dagre center coordinates to Vue Flow top-left coordinates. Catch layout errors and return a deterministic grid fallback.

```ts
export type WorkflowPosition = { x: number; y: number }

export function layoutWorkflowGraph(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): Map<string, WorkflowPosition> {
  // Sorted Dagre input, top-left coordinate conversion, and grid fallback.
}
```

- [ ] **Step 4: Run focused tests**

Run: `npm run test -- workflowLayout.test.ts`

Expected: PASS.

### Task 2: Rebuild AgentFlow Around Current Visible State

**Files:**
- Modify: `web/src/components/AgentFlow.vue`
- Modify: `web/src/views/ReviewView.vue`

**Interfaces:**
- Consumes: `workflowNodes`, `workflowEdges`, `selectedNodeId`.
- Produces: the existing `select(nodeId)` event plus a graph toolbar that accepts the existing replay controls slot.

- [ ] **Step 1: Replace final-result layout props**

Remove `layoutWorkflowNodes`, `layoutWorkflowEdges`, and `layoutKey` from `AgentFlow` props and its `ReviewView` call site. Compute positions exclusively with `layoutWorkflowGraph(displayGraph.nodes, displayGraph.edges)`.

- [ ] **Step 2: Add stable anchors and edge hierarchy**

Set every node to `sourcePosition: Position.Bottom` and `targetPosition: Position.Top`. Keep primary relationships on `smoothstep`, apply semantic classes, use relation-colored marker objects, and add a focused-edge class for edges connected to the current branch.

```ts
return {
  sourcePosition: Position.Bottom,
  targetPosition: Position.Top,
  position: layoutPositions.value.get(item.id) ?? { x: 0, y: 0 },
}
```

- [ ] **Step 3: Make reflow and viewport motion restrained**

Apply a transform transition to Vue Flow nodes. On initial load call `fitView`; on later additions call `fitView` with a minimum zoom guard and broad padding rather than `fitBounds` on one node. Status-only changes must not move the viewport.

- [ ] **Step 4: Consolidate graph chrome**

Merge graph heading, node count, replay slot, focus status, and zoom actions into a compact toolbar. Remove duplicate focus text. Give nodes fixed geometry matching `WORKFLOW_NODE_SIZES`, increase readable text sizes, and ensure text clamping cannot change dimensions.

- [ ] **Step 5: Run graph tests and typecheck**

Run: `npm run test -- workflowLayout.test.ts && npm run typecheck`

Expected: PASS.

### Task 3: Restructure the Review Workbench

**Files:**
- Modify: `web/src/views/ReviewView.vue`
- Modify: `web/src/components/ReviewForm.vue`
- Modify: `web/src/components/DispatchBoard.vue`
- Modify: `web/src/components/ThoughtStream.vue`
- Modify: `web/src/components/FindingCard.vue`

**Interfaces:**
- Consumes: existing Store getters/actions and existing component events.
- Produces: local `leftRailCollapsed`, `rightRailCollapsed`, and `eventsExpanded` UI state with no Store changes.

- [ ] **Step 1: Build the full-height workbench grid**

Replace the command band plus fixed three-column cockpit with a run bar and `grid-template-columns` driven by collapse classes. Keep the task graph central and allocate it the largest track.

```vue
<section class="workbench" :class="{ 'left-collapsed': leftRailCollapsed, 'right-collapsed': rightRailCollapsed }">
  <aside class="dispatch-rail">...</aside>
  <main class="graph-workspace">...</main>
  <aside class="findings-rail">...</aside>
</section>
```

- [ ] **Step 2: Make the run form a compact toolbar**

Keep existing validation and submit events. Use explicit labels for accessibility, compact inputs, a primary start button, and an icon-led demo action. Show the active Run ID as a stable status item.

- [ ] **Step 3: Remove duplicated low-value panel content**

Keep concurrency metrics, missions, and the latest dispatch decisions in the left rail. Move recent runs and changed-file aggregation into compact sections that do not dominate the running state. Add collapse buttons with tooltips to both rails.

- [ ] **Step 4: Convert ThoughtStream to a bottom drawer**

Keep the last event summary visible when collapsed and use a fixed-height scrolling list when expanded. Preserve automatic scrolling only while expanded.

- [ ] **Step 5: Tighten Finding cards and empty states**

Keep severity, file, title, verdict, and navigation behavior. Reduce decorative framing, improve scanning, and make the zero-Finding state compact in the right rail.

- [ ] **Step 6: Run component and Store tests**

Run: `npm run test`

Expected: all existing replay and Store tests PASS.

### Task 4: Unify the Global Windows Visual System

**Files:**
- Modify: `web/src/styles.css`
- Modify: `web/src/theme.ts`
- Modify: `web/src/App.vue`

**Interfaces:**
- Consumes: existing semantic token names used by all components.
- Produces: additional semantic tokens for workbench dimensions and interactive surface states without raw colors.

- [ ] **Step 1: Refine tokens and base typography**

Increase default readability, add workbench bar/rail dimension tokens, define shared focus rings, and keep the palette multi-accent rather than monochromatic.

- [ ] **Step 2: Rebuild the application bar**

Use a Windows-workbench density: stable product mark, clear text navigation, API status with label, and consistent hover/active/focus feedback. Remove mobile-only text-hiding rules from this round.

- [ ] **Step 3: Add shared utility patterns**

Define reusable classes for panel headings, icon buttons, empty copy, mono counters, and scroll areas only where at least two pages consume them.

- [ ] **Step 4: Run lint and typecheck**

Run: `npm run lint && npm run typecheck`

Expected: PASS with zero errors.

### Task 5: Align Diff and Benchmark Pages

**Files:**
- Modify: `web/src/views/DiffView.vue`
- Modify: `web/src/views/BenchmarkView.vue`

**Interfaces:**
- Consumes: existing Store state, benchmark endpoint, ECharts option, Naive data table, and toast providers.
- Produces: no new cross-page API.

- [ ] **Step 1: Align Diff workspace chrome**

Use the shared page toolbar, a stable code/finding split, sticky finding detail, clearer selected flagged lines, and preserved copy action. Keep code horizontal scrolling inside the code pane.

- [ ] **Step 2: Align Benchmark hierarchy**

Use the same page toolbar and panel headings, make metric values and targets easier to compare, improve data-source labeling, and retain skeletons/table overflow.

- [ ] **Step 3: Run full static checks**

Run: `npm run typecheck && npm run lint && npm run build`

Expected: PASS and production assets emitted to `web/dist`.

### Task 6: Windows Desktop Browser Verification

**Files:**
- Modify only files from Tasks 1-5 when verification exposes a concrete defect.

**Interfaces:**
- Consumes: local Vite server and Demo workflow.
- Produces: verified Review, Diff, and Benchmark pages at all target Windows viewport sizes.

- [ ] **Step 1: Verify Review at 1366x768**

Open Demo replay, observe incremental nodes, and confirm the graph remains the primary area, reflow is smooth, edges enter top and leave bottom, no node is enlarged to fill the canvas, and rails/toolbars do not overlap.

- [ ] **Step 2: Verify 1536x864 and 1920x1080**

Confirm collapsed and expanded rails, event drawer, graph zoom controls, Finding selection, and page scrolling. Check `document.body.scrollWidth === document.body.clientWidth`.

- [ ] **Step 3: Verify Diff and Benchmark**

Open Demo Diff and Benchmark at 1366x768 and 1920x1080. Confirm code scrolling stays inside its pane, finding details remain visible, chart is nonblank, table headers and values fit, and loading/error states remain usable.

- [ ] **Step 4: Inspect browser errors**

Read console errors from the local app and fix application errors. Ignore only external telemetry failures emitted by the host environment.

- [ ] **Step 5: Run final verification**

Run: `npm run typecheck && npm run lint && npm run test && npm run build`

Expected: all commands PASS.
