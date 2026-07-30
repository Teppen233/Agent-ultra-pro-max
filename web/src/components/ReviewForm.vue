<script setup lang="ts">
import { Play, WandSparkles } from 'lucide-vue-next'
import { NButton, NInput } from 'naive-ui'
import { ref } from 'vue'

defineProps<{ loading: boolean }>()
const emit = defineEmits<{
  submit: [prUrl: string, repoPath: string]
  demo: []
}>()

const prUrl = ref('')
const repoPath = ref('')

function submit() {
  if (prUrl.value.trim() && repoPath.value.trim()) {
    emit('submit', prUrl.value.trim(), repoPath.value.trim())
  }
}
</script>

<template>
  <form class="review-form" @submit.prevent="submit">
    <NInput v-model:value="prUrl" aria-label="GitHub PR URL 或本地 Diff 路径" placeholder="GitHub PR URL 或本地 .diff 路径" clearable />
    <NInput v-model:value="repoPath" aria-label="本地仓库绝对路径" placeholder="本地仓库绝对路径" clearable />
    <NButton attr-type="submit" type="primary" :loading="loading" :disabled="!prUrl.trim() || !repoPath.trim()">
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
  grid-template-columns: minmax(14rem, 1.45fr) minmax(12rem, 1fr) auto auto;
}
</style>
