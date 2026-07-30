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
    <NInput v-model:value="prUrl" size="large" placeholder="GitHub PR URL 或本地 .diff 路径" clearable />
    <NInput v-model:value="repoPath" size="large" placeholder="本地仓库绝对路径" clearable />
    <NButton attr-type="submit" type="primary" size="large" :loading="loading" :disabled="!prUrl.trim() || !repoPath.trim()">
      <template #icon>
        <Play :size="16" />
      </template>
      开始审查
    </NButton>
    <NButton size="large" secondary @click="emit('demo')">
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
  grid-template-columns: minmax(15rem, 1.5fr) minmax(13rem, 1fr) auto auto;
}

@media (max-width: 900px) {
  .review-form {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 560px) {
  .review-form {
    grid-template-columns: 1fr;
  }
}
</style>
