<script setup lang="ts">
import type { OperationCategory, OperationRecord } from '@/contracts'

defineProps<{ operations: OperationRecord[] }>()

const categoryText: Record<OperationCategory, string> = {
  plan: '计划', tool: '工具', mailbox: '协作', candidate: '候选', verdict: '裁决',
}
const statusText: Record<OperationRecord['status'], string> = {
  started: '进行中', completed: '已完成', failed: '失败', published: '已发布',
  pending: '待验证', accepted: '已接受', rejected: '已拒绝',
}
</script>

<template>
  <section class="operation-feed panel">
    <div class="section-heading compact">
      <div><span class="eyebrow">真实执行记录</span><h2>审查操作流水线</h2></div>
      <b>{{ operations.length }}</b>
    </div>
    <div class="operation-list">
      <article v-for="operation in [...operations].reverse()" :key="operation.id" :class="operation.category">
        <header>
          <span :class="['operation-tag', operation.category]">{{ categoryText[operation.category] }}</span>
          <strong>{{ operation.actor }} · {{ operation.action }}</strong>
          <time>{{ new Date(operation.timestamp).toLocaleTimeString('zh-CN', { hour12: false }) }}</time>
        </header>
        <p v-if="operation.target"><b>目标：</b>{{ operation.target }}</p>
        <p><b>结果：</b>{{ operation.summary }}</p>
        <footer>
          <span>{{ statusText[operation.status] }}</span>
          <span v-if="operation.durationMs !== undefined">{{ operation.durationMs }}ms</span>
          <span v-if="operation.resultCount !== undefined">{{ operation.resultCount }} 项结果</span>
        </footer>
      </article>
      <p v-if="!operations.length" class="empty-state">计划、工具、协作、候选与裁决会以中文显示在这里。</p>
    </div>
  </section>
</template>
