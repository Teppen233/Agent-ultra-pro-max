<script setup lang="ts">
import { Play, WandSparkles } from 'lucide-vue-next'
import { NButton, NCheckbox, NInput, NTooltip } from 'naive-ui'
import { computed, ref } from 'vue'

const props = defineProps<{
  loading: boolean
  benchmarkCount?: number
  benchmarkCapacity?: number
  benchmarkAvailable?: boolean
}>()
const emit = defineEmits<{
  submit: [prUrl: string, repoPath: string, addToBenchmark: boolean]
  demo: []
}>()

const prUrl = ref('')
const repoPath = ref('')
const addToBenchmark = ref(false)
const benchmarkFull = computed(
  () => (props.benchmarkCount ?? 0) >= (props.benchmarkCapacity ?? 5),
)
const benchmarkHint = computed(() => {
  if (!props.benchmarkAvailable) return 'Benchmark 服务暂不可用'
  if (benchmarkFull.value) return 'Benchmark 已满，请先保留当前 5 个仓库'
  return '审计成功后保存当前结果，不会重复运行'
})
const benchmarkCapacityLabel = computed(() =>
  props.benchmarkAvailable
    ? `${props.benchmarkCount ?? 0} / ${props.benchmarkCapacity ?? 5}`
    : '暂不可用',
)

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
      <NTooltip>
        <template #trigger>
          <NCheckbox
            v-model:checked="addToBenchmark"
            aria-label="加入 Benchmark"
            :disabled="!props.benchmarkAvailable || !isGithubPr(prUrl) || benchmarkFull"
          >
            加入 Benchmark
          </NCheckbox>
        </template>
        {{ benchmarkHint }}
      </NTooltip>
      <span class="benchmark-capacity">
        {{ benchmarkCapacityLabel }}
      </span>
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
  color: var(--color-muted);
  font-size: 0.75rem;
}

@media (max-width: 1450px) {
  .review-form {
    grid-template-columns: minmax(14rem, 1.45fr) minmax(12rem, 1fr) auto auto;
  }

  .benchmark-option {
    grid-column: 1 / 3;
    grid-row: 2;
  }
}
</style>
