<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { startReview } from '@/api/client'
import { useReviewStore } from '@/stores/review'

const router = useRouter()
const store = useReviewStore()
const mode = ref<'github' | 'local'>('github')
const prUrl = ref('https://github.com/acme/payments-api/pull/284')
const repoPath = ref('D:\\workspace\\payments-api')
const baseRef = ref('main')
const headRef = ref('feature/bulk-refund')
const loading = ref(false)
const error = ref('')

const submit = async (): Promise<void> => {
  loading.value = true
  error.value = ''
  store.reset()
  try {
    const request = mode.value === 'github'
      ? { pr_url: prUrl.value.trim() }
      : { repo_path: repoPath.value.trim(), base_ref: baseRef.value.trim(), head_ref: headRef.value.trim() }
    const result = await startReview(request)
    await router.push({ name: 'review', params: { runId: result.run_id } })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法启动审查，请稍后重试。'
  } finally {
    loading.value = false
  }
}

const playDemo = async (): Promise<void> => {
  store.reset()
  await router.push({ name: 'review', params: { runId: 'demo-security-20260730' }, query: { demo: '1' } })
}
</script>

<template>
  <div class="start-page page-width">
    <section class="hero">
      <div class="hero-copy">
        <span class="hero-badge"><i /> MULTI-AGENT CODE INTELLIGENCE</span>
        <h1>让每一行改动，<br><em>都经得起独立验证。</em></h1>
        <p>两位专家并行寻找可证伪的缺陷假设，Verifier 负责反证与裁决。只发布有修改行定位、有触发条件、有实际影响的问题。</p>
        <div class="hero-proof">
          <span><b>2×</b> 并行专家</span><span><b>1×</b> 独立验证</span><span><b>600s</b> 硬预算</span>
        </div>
      </div>
      <div class="launch-card panel">
        <div class="launch-head"><div><span class="eyebrow">START A REVIEW</span><h2>发起代码审查</h2></div><span class="secure-chip">只读访问</span></div>
        <div class="mode-tabs">
          <button :class="{ active: mode === 'github' }" @click="mode = 'github'">GitHub PR</button>
          <button :class="{ active: mode === 'local' }" @click="mode = 'local'">本地仓库</button>
        </div>
        <form @submit.prevent="submit">
          <template v-if="mode === 'github'">
            <label for="pr-url">Pull Request 地址</label>
            <div class="input-shell"><span>⌘</span><input id="pr-url" v-model="prUrl" type="url" required placeholder="https://github.com/org/repo/pull/123"></div>
          </template>
          <template v-else>
            <label for="repo-path">本地仓库路径</label>
            <div class="input-shell"><span>⌁</span><input id="repo-path" v-model="repoPath" required></div>
            <div class="two-fields"><div><label for="base-ref">基准引用</label><input id="base-ref" v-model="baseRef" required></div><div><label for="head-ref">目标引用</label><input id="head-ref" v-model="headRef" required></div></div>
          </template>
          <p v-if="error" class="form-error">{{ error }}</p>
          <button class="primary-button" type="submit" :disabled="loading"><span>{{ loading ? '正在创建运行…' : '启动真实审查' }}</span><b>→</b></button>
        </form>
        <div class="demo-divider"><span>或使用稳定演示模式</span></div>
        <button class="demo-button" @click="playDemo"><span class="play-icon">▶</span><span><strong>播放最佳离线 Replay</strong><small>无需后端、模型或网络 · 约 6 秒</small></span><b>DEMO</b></button>
      </div>
    </section>
    <section class="capability-strip">
      <article><span>01</span><div><strong>Diff 中心</strong><small>聚焦修改行和关联上下文</small></div></article>
      <article><span>02</span><div><strong>流式协作</strong><small>候选产生后立即进入验证</small></div></article>
      <article><span>03</span><div><strong>证据优先</strong><small>触发条件、影响、代码定位</small></div></article>
      <article><span>04</span><div><strong>稳定回放</strong><small>比赛现场不依赖外部服务</small></div></article>
    </section>
  </div>
</template>
