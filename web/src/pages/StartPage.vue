<template>
  <div class="start-page">
    <div class="hero">
      <h2>智能代码审查</h2>
      <p>由多个 AI Agent 并行协作，自动检测缺陷、分析意图、交叉验证，生成专业审查报告。</p>
    </div>

    <div class="mode-tabs">
      <button :class="['tab', { active: mode === 'pr' }]" @click="mode = 'pr'">PR 审查</button>
      <button :class="['tab', { active: mode === 'local' }]" @click="mode = 'local'">本地仓库</button>
      <button :class="['tab', { active: mode === 'replay' }]" @click="mode = 'replay'">Replay</button>
    </div>

    <!-- PR 模式 -->
    <div v-if="mode === 'pr'" class="form-card">
      <label class="label">GitHub PR 地址</label>
      <input
        v-model="prUrl"
        class="input"
        placeholder="https://github.com/owner/repo/pull/123"
        :disabled="submitting"
        autofocus
        @keydown.enter="handleStart"
      />
      <button class="btn btn-primary" :disabled="!prUrl.trim() || submitting" @click="handleStart">
        <span v-if="submitting" class="spinner"></span>
        {{ submitting ? '启动中...' : '开始审查' }}
      </button>
      <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>
    </div>

    <!-- 本地模式 -->
    <div v-if="mode === 'local'" class="form-card">
      <label class="label">仓库路径</label>
      <input
        v-model="repoPath"
        class="input"
        placeholder="d:/projects/my-repo"
        :disabled="submitting"
        @keydown.enter="handleStart"
      />
      <div class="form-row">
        <div class="form-group">
          <label class="label">基线分支</label>
          <input v-model="baseRef" class="input" placeholder="main" :disabled="submitting" />
        </div>
        <div class="form-group">
          <label class="label">目标分支</label>
          <input v-model="headRef" class="input" placeholder="feature/xxx" :disabled="submitting" />
        </div>
      </div>
      <button
        class="btn btn-primary"
        :disabled="!repoPath.trim() || submitting"
        @click="handleStart"
      >
        <span v-if="submitting" class="spinner"></span>
        {{ submitting ? '启动中...' : '开始审查' }}
      </button>
      <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>
    </div>

    <!-- Replay 模式 -->
    <div v-if="mode === 'replay'" class="form-card">
      <label class="label">审查 Run ID</label>
      <input
        v-model="replayRunId"
        class="input"
        placeholder="输入已有的 run_id"
        :disabled="submitting"
        @keydown.enter="handleStart"
      />
      <button
        class="btn btn-primary"
        :disabled="!replayRunId.trim() || submitting"
        @click="handleStart"
      >
        <span v-if="submitting" class="spinner"></span>
        {{ submitting ? '加载中...' : '开始重放' }}
      </button>
      <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { startReview } from '../api/client'
import type { ReviewRequest } from '../contracts'

const router = useRouter()

const mode = ref<'pr' | 'local' | 'replay'>('pr')
const prUrl = ref('')
const repoPath = ref('')
const baseRef = ref('main')
const headRef = ref('')
const replayRunId = ref('')
const submitting = ref(false)
const errorMsg = ref('')

async function handleStart() {
  errorMsg.value = ''

  // PR 模式 URL 格式校验
  if (mode.value === 'pr' && prUrl.value.trim()) {
    if (!/^https?:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+/.test(prUrl.value.trim())) {
      errorMsg.value = '请输入有效的 GitHub PR URL，如 https://github.com/owner/repo/pull/123'
      return
    }
  }

  submitting.value = true

  try {
    let request: ReviewRequest = {}

    if (mode.value === 'pr') {
      request = { pr_url: prUrl.value.trim() }
    } else if (mode.value === 'local') {
      request = {
        repo_path: repoPath.value.trim(),
        base_ref: baseRef.value.trim() || undefined,
        head_ref: headRef.value.trim() || undefined,
      }
    } else if (mode.value === 'replay') {
      request = { replay_run_id: replayRunId.value.trim() }
    }

    const result = await startReview(request)
    router.push({ name: 'review', params: { runId: result.run_id } })
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : '启动失败，请重试'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.start-page {
  max-width: 640px;
  margin: 48px auto;
}

.hero {
  text-align: center;
  margin-bottom: 32px;
}

.hero h2 {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 8px;
}

.hero p {
  color: var(--color-text-muted);
  font-size: 15px;
}

.mode-tabs {
  display: flex;
  gap: 0;
  margin-bottom: 24px;
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--color-border);
  background: var(--color-border);
}

.tab {
  flex: 1;
  padding: 10px 16px;
  border: none;
  background: var(--color-surface);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  color: var(--color-text-muted);
  transition: all 0.15s;
}

.tab.active {
  background: var(--color-primary);
  color: #fff;
}

.form-card {
  background: var(--color-surface);
  border-radius: var(--radius);
  padding: 24px;
  box-shadow: var(--shadow);
}

.label {
  display: block;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 6px;
}

.input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  font-size: 14px;
  margin-bottom: 16px;
  transition: border-color 0.15s;
}

.input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-row {
  display: flex;
  gap: 12px;
}

.form-group {
  flex: 1;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 24px;
  border: none;
  border-radius: var(--radius);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-primary {
  background: var(--color-primary);
  color: #fff;
  width: 100%;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.error-msg {
  color: var(--color-danger);
  font-size: 13px;
  margin-top: 8px;
}
</style>
