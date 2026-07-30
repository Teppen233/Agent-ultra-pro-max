<script setup lang="ts">
import { Play, WandSparkles } from 'lucide-vue-next'
import { NButton, NCheckbox, NInput } from 'naive-ui'
import { ref } from 'vue'

const props = defineProps<{
  loading: boolean
  benchmarkCount?: number
  benchmarkCapacity?: number
}>()
const emit = defineEmits<{
  submit: [prUrl: string, repoPath: string, addToBenchmark: boolean]
  demo: []
}>()

const prUrl = ref('')
const repoPath = ref('')
const addToBenchmark = ref(false)

function isGithubPr(value: string): boolean {
  return /^https?:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/\d+(?:[/?#].*)?$/i.test(value.trim())
}

function submit() {
  if (prUrl.value.trim()) {
    emit('submit', prUrl.value.trim(), repoPath.value.trim(), addToBenchmark.value)
  }
}
</script>

<template>
  <form class="review-form" @submit.prevent="submit">
    <NInput v-model:value="prUrl" aria-label="GitHub PR URL 或本地 Diff 路径" placeholder="GitHub PR URL 或本地 .diff 路径" clearable />
    <NInput
      v-model:value="repoPath"
      aria-label="本地仓库绝对路径（可选）"
      placeholder="可选；PR 留空自动拉取，本地 Diff 必填"
      clearable
    />
    <div class="benchmark-option">
      <NCheckbox
        v-model:checked="addToBenchmark"
        :disabled="!isGithubPr(prUrl) || (props.benchmarkCount ?? 0) >= (props.benchmarkCapacity ?? 5)"
      >
        加入 Benchmark
      </NCheckbox>
      <span class="benchmark-capacity">{{ props.benchmarkCount ?? 0 }} / {{ props.benchmarkCapacity ?? 5 }}</span>
    </div>
    <NButton attr-type="submit" type="primary" :loading="loading" :disabled="!prUrl.trim()">
      <template #icon>
        <Play :size="16" />
      </template>
      开始审查
    </NButton>
    <NButton secondary @click="emit('demo')">
      <template #icon>
        <WandSparkles :size="16" />
      </template>
      演示回放
    </NButton>
  </form>
</template>

<style scoped>
.review-form {
  display: grid;
  gap: var(--space-2);
  grid-template-columns: minmax(14rem, 1.45fr) minmax(12rem, 1fr) auto auto auto;
}

.benchmark-option {
  align-items: center;
  display: flex;
  gap: var(--space-1);
  white-space: nowrap;
}

.benchmark-capacity {
  color: var(--text-muted);
  font-size: 0.75rem;
}
</style>
