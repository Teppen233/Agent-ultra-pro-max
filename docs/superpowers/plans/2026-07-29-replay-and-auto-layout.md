# Controllable Replay And Auto Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add immediately updating recent runs, controllable event replay, and non-overlapping automatically focused workflow layout.

**Architecture:** Pinia owns one event reducer for live, history, and demo sources. Completed runs retain their full event list for deterministic seek and step operations; incomplete runs reconnect to SSE and append events. AgentFlow uses Dagre for stable top-to-bottom placement and Vue Flow viewport APIs for focus.

**Tech Stack:** Vue 3, TypeScript strict, Pinia, Naive UI, Vue Flow, `@dagrejs/dagre`, Vitest.

## Global Constraints

- Speeds are exactly `0.5x`, `1x`, `2x`, and `4x`; `1x` uses a deliberately readable compressed delay.
- Previous, next, seek, restart, play, and pause must operate without backend requests.
- Route changes between recent runs must update the page without refresh.
- Graph nodes must never overlap; graph canvas remains pannable and zoomable.
- All visible copy is Simplified Chinese and all controls use existing design tokens.
- TypeScript strict, ESLint, Vitest, and production build must pass.

---

### Task 1: Deterministic Replay Store

**Files:**
- Modify: `web/src/stores/review.ts`
- Test: `web/src/stores/review.test.ts`

**Interfaces:**
- Produces: `ReplaySpeed = 0.5 | 1 | 2 | 4` and store actions `setReplaySource`, `playReplay`, `pauseReplay`, `seekReplay`, `stepReplay`, `restartReplay`, `connectLive`.
- Consumes: existing `PipelineEvent`, `RunDetail`, and `consume(event)` reducer.

- [ ] **Step 1: Write failing replay state tests**

```ts
store.setReplaySource(demoEvents, true)
expect(store.replayIndex).toBe(demoEvents.length)
store.stepReplay(-1)
expect(store.replayIndex).toBe(demoEvents.length - 1)
store.seekReplay(0)
expect(store.workflowNodes).toHaveLength(0)
store.setReplaySpeed(4)
expect(store.replaySpeed).toBe(4)
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `cd web && npm run test -- src/stores/review.test.ts`

Expected: FAIL because replay state and actions do not exist.

- [ ] **Step 3: Implement the replay state machine**

Add state for `replayEvents`, `replayIndex`, `replaySpeed`, `replaying`, `replayTimer`, and `live`. Split visual clearing from source clearing. Rebuild seek state by clearing visual collections and consuming `replayEvents.slice(0, index)`. Schedule the next event with:

```ts
const rawDelay = Math.max(0, next.timestamp - current.timestamp) * 1000
const delay = Math.min(900, Math.max(220, rawDelay)) / replaySpeed
```

At the end, retain final state and stop the timer. Live SSE appends each event to `replayEvents`; a report closes the stream and leaves the completed source replayable.

- [ ] **Step 4: Run store tests**

Run: `cd web && npm run test -- src/stores/review.test.ts`

Expected: PASS.

### Task 2: Replay Controls And Route Synchronization

**Files:**
- Create: `web/src/components/ReplayControls.vue`
- Modify: `web/src/views/ReviewView.vue`
- Modify: `web/src/components/ReviewForm.vue`
- Test: `web/src/components/ReplayControls.test.ts`

**Interfaces:**
- Consumes: replay state and actions from Task 1.
- Produces: `ReplayControls` props `index`, `total`, `playing`, `speed`, `live`; emits `restart`, `previous`, `toggle`, `next`, `seek`, and `speed`.

- [ ] **Step 1: Write failing component tests**

```ts
const wrapper = mount(ReplayControls, { props: { index: 3, total: 10, playing: false, speed: 1, live: false } })
await wrapper.get('[data-testid="replay-next"]').trigger('click')
expect(wrapper.emitted('next')).toHaveLength(1)
expect(wrapper.text()).toContain('3 / 10')
```

- [ ] **Step 2: Run the focused component test and confirm failure**

Run: `cd web && npm run test -- src/components/ReplayControls.test.ts`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Build the control bar**

Use `NButton`, `NTooltip`, `NSlider`, `NRadioGroup`, and `NRadioButton`, with Lucide `RotateCcw`, `SkipBack`, `Play`, `Pause`, and `SkipForward`. Disable manual controls in live mode and use the exact four speed options.

- [ ] **Step 4: Watch route identity instead of mounting once**

Replace the one-time route load with an immediate watcher of `route.params.runId`. Each change cancels old playback and streams, then loads the selected run. Completed runs call `setReplaySource(events, true)`; incomplete runs call `connectLive(runId)`. Demo uses the same replay source and player.

- [ ] **Step 5: Run component and store tests**

Run: `cd web && npm run test`

Expected: PASS.

### Task 3: Dagre Layout And Automatic Focus

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Modify: `web/src/components/AgentFlow.vue`

**Interfaces:**
- Consumes: `workflowNodes`, `workflowEdges`, and stable node IDs.
- Produces: Dagre-computed Vue Flow `Node.position` values and viewport focus behavior.

- [ ] **Step 1: Add the layout dependency**

Run: `cd web && npm install @dagrejs/dagre`

Expected: dependency and lockfile contain `@dagrejs/dagre`.

- [ ] **Step 2: Replace fixed lanes with layered layout**

Build a Dagre graph with `rankdir: 'TB'`, stable node dimensions, `nodesep: 56`, and `ranksep: 84`. Rank only forward edges; omit reverse evidence/result edges from ranking while still rendering them. Convert Dagre center coordinates to Vue Flow top-left positions.

- [ ] **Step 3: Add focus rules**

Watch `id:status` signatures. A single new or newly running node calls `fitView({ nodes: [id], padding: 1.2, duration: 420, maxZoom: 0.9 })`; a batch load calls full `fitView`. Remove the fixed 36rem canvas height and use a viewport-height minimum while preserving pan and zoom.

- [ ] **Step 4: Run full frontend gates**

Run: `cd web && npm run typecheck && npm run lint && npm run test && npm run build`

Expected: all commands pass.

### Task 4: Browser And Integration Verification

**Files:**
- Modify only if verification exposes a scoped defect.

**Interfaces:**
- Consumes: running Vite frontend and FastAPI backend.
- Produces: verified user workflow at `/review`.

- [ ] **Step 1: Verify route updates and history controls**

Open two different recent runs without refresh. Confirm run ID, graph, Findings, and replay total change. Exercise restart, next, previous, play, pause, seek, and every speed.

- [ ] **Step 2: Verify graph layout**

Replay a large real run. Measure every node rectangle pair and require zero overlaps. Confirm new running nodes enter the viewport and the user can still pan/zoom.

- [ ] **Step 3: Verify responsive behavior**

At desktop and `390x844`, require `document.documentElement.scrollWidth === innerWidth`, readable controls, and no fresh console errors.

- [ ] **Step 4: Run all project gates**

Run backend tests, Ruff, Mypy, frontend typecheck, ESLint, Vitest, and build. Keep frontend at `http://127.0.0.1:5175/review` and backend at `http://127.0.0.1:8000`.
