export type StageName = 'preprocess' | 'context' | 'review' | 'verify' | 'report'
export type AgentName = 'coordinator' | 'defect' | 'intent' | 'verifier'
export type Severity = 'critical' | 'high' | 'medium' | 'low'
export type Category = 'logic' | 'security' | 'memory' | 'architecture' | 'static'
export type WorkflowStatus =
  | 'queued'
  | 'running'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'cancelled'
export type WorkflowKind =
  | 'input'
  | 'coordinator'
  | 'agent_task'
  | 'tool'
  | 'finding'
  | 'verifier'
  | 'report'
export type WorkflowRelation =
  | 'dispatch'
  | 'depends_on'
  | 'tool_call'
  | 'evidence'
  | 'handoff'
  | 'candidate'
  | 'challenge'
  | 'result'

export interface WorkflowNode {
  id: string
  kind: WorkflowKind
  label: string
  status: WorkflowStatus
  agent?: AgentName | null
  detail?: string | null
  task_id?: string | null
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  relation: WorkflowRelation
}

export interface Finding {
  id: string
  source_id?: string
  category: Category
  severity: Severity
  confidence: number
  file: string
  line_start: number
  line_end: number
  title: string
  reasoning: string
  trigger_path: string
  suggestion: string
  verdict?: 'keep' | 'reject' | null
  verdict_reason?: string | null
  confidence_adjusted?: number | null
}

export interface Verdict {
  finding_id: string
  verdict: 'keep' | 'reject'
  reason: string
  confidence_adjusted: number
}

interface EventBase {
  timestamp: number
  task_id?: string | null
}

export type PipelineEvent =
  | (EventBase & { type: 'run' })
  | (EventBase & {
      type: 'stage'
      stage: StageName
      status: 'start' | 'done' | 'error'
      elapsed?: number
      text?: string
    })
  | (EventBase & { type: 'workflow_node'; workflow_node: WorkflowNode })
  | (EventBase & { type: 'workflow_edge'; workflow_edge: WorkflowEdge })
  | (EventBase & {
      type: 'agent'
      agent: AgentName
      agent_status: 'running' | 'done' | 'error'
    })
  | (EventBase & { type: 'thought'; agent: AgentName; text: string })
  | (EventBase & {
      type: 'tool'
      agent: AgentName
      tool: string
      args?: Record<string, unknown>
      result?: string
    })
  | (EventBase & {
      type: 'snapshot'
      text?: string
      snapshot_findings?: Finding[]
    })
  | (EventBase & { type: 'finding'; finding: Finding })
  | (EventBase & { type: 'verdict'; verdict: Verdict })
  | (EventBase & { type: 'report'; markdown: string; findings?: Finding[] })

export interface DispatchEntry {
  id: string
  timestamp: number
  title: string
  detail: string
  tone: 'neutral' | 'active' | 'success' | 'danger'
}

export interface RunSummary {
  run_id: string
  status: 'running' | 'done' | 'failed'
  event_count: number
  has_error: boolean
}

export interface RunDetail {
  run_id: string
  events: PipelineEvent[]
  report: string | null
  diff: string | null
}

export interface BenchmarkRow {
  repo: string
  pr_url: string
  category: Category
  hit: boolean
  reason: string
  finding_count: number
  elapsed_seconds: number
}
