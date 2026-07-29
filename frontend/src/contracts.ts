/** ReviewCrew 对外公开的事件名称；与后端 EventType 冻结契约保持一致。 */
export type EventType =
  | 'review.started'
  | 'review.completed'
  | 'review.failed'
  | 'stage.started'
  | 'stage.completed'
  | 'stage.failed'
  | 'agent.started'
  | 'agent.tool'
  | 'agent.candidate'
  | 'agent.completed'
  | 'agent.failed'
  | 'verifier.started'
  | 'verifier.accepted'
  | 'verifier.rejected'
  | 'verifier.completed'
  | 'report.generated'

/** SSE 与 Replay 共用的六字段公开事件。 */
export interface PipelineEvent {
  id: string
  run_id: string
  sequence: number
  timestamp: string
  type: EventType
  data: Record<string, unknown>
}

export type ReviewStatus = 'idle' | 'running' | 'completed' | 'partial' | 'failed'
export type AgentRole = 'defect' | 'intent' | 'verifier'
export type AgentStatus = 'waiting' | 'running' | 'completed' | 'degraded' | 'failed'
export type VerdictStatus = 'pending' | 'accepted' | 'rejected'

export interface CodeEvidence {
  source?: string
  file: string
  start_line: number
  end_line: number
  description: string
  content: string
}

/** 兼容实时摘要和最终报告中的完整 Finding。 */
export interface Finding {
  id: string
  producer?: 'defect' | 'intent'
  category?: string
  severity?: 'critical' | 'high' | 'medium' | 'low'
  confidence?: number
  file?: string
  line_start?: number
  line_end?: number
  line?: number
  title?: string
  description?: string
  trigger_condition?: string
  trigger?: string
  impact?: string
  reasoning_summary?: string
  suggestion?: string
  recommendation?: string
  evidence?: CodeEvidence[]
  created_at?: string
}

export interface CandidateRecord {
  finding: Finding
  agent: AgentRole
  verdict: VerdictStatus
  verdictCode?: string
  verdictReason?: string
  verdictConfidence?: number
}

export interface AgentState {
  role: AgentRole
  label: string
  status: AgentStatus
  tools: string[]
  candidateCount: number
  warning?: string
}

export interface StageState {
  id: string
  label: string
  status: 'waiting' | 'running' | 'completed' | 'failed'
}

export interface ReviewRequest {
  pr_url?: string
  repo_path?: string
  base_ref?: string
  head_ref?: string
  replay_run_id?: string
}

export interface StartReviewResponse {
  run_id: string
  status: string
}

export interface ReviewResult {
  run_id: string
  status: 'completed' | 'partial' | 'failed'
  repository: string
  base_sha: string
  head_sha: string
  findings: Finding[]
  rejected_count: number
  coverage: string[]
  warnings: string[]
  started_at: string
  completed_at: string
  elapsed_seconds: number
}

export interface ReviewPendingResponse {
  kind: 'pending'
  run_id: string
  status: string
}

export type ReviewResponse =
  | ReviewPendingResponse
  | { kind: 'result'; result: ReviewResult }

export interface RunSummary {
  run_id: string
  status: string
}

export interface RunsResponse {
  runs: RunSummary[]
  total: number
  limit: number
  offset: number
}

export interface BenchmarkSummary {
  mode: 'quick' | 'case' | 'full'
  runner: 'fake' | 'real'
  offline: boolean
  selected_cases: number
  completed_cases: number
  actually_run_ready_cases: number
  caught_cases: number
  real_catch_rate: number | null
  observed_offline_catch_rate: number | null
  offline_results_excluded_from_real_rate: boolean
  false_positive_count: number
  verifier_accepted_count: number
  verifier_rejected_count: number
  needs_human_review_cases: number
  timed_out_cases: number
  elapsed_seconds: number
}
