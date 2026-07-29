/** 前端协议定义 —— 与后端 PipelineEvent 保持一致。 */

export interface PipelineEvent {
  id: string
  run_id: string
  sequence: number
  timestamp: string
  type: EventType
  data: Record<string, unknown>
}

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

export interface ReviewRequest {
  pr_url?: string
  repo_path?: string
  base_ref?: string
  head_ref?: string
  replay_run_id?: string
}

export interface Finding {
  id: string
  producer: 'defect' | 'intent'
  category: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  confidence: number
  file: string
  line_start: number
  line_end: number
  title: string
  description: string
  trigger_condition: string
  impact: string
  reasoning_summary: string
  suggestion?: string
}

export type ReviewStatus = 'idle' | 'loading' | 'reviewing' | 'verifying' | 'completed' | 'failed'
