<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

const props = withDefaults(defineProps<{ startedAt?: string; completedAt?: string; maxSeconds?: number }>(), { startedAt: '', completedAt: '', maxSeconds: 600 })
const now = ref(Date.now())
const timer = window.setInterval(() => { now.value = Date.now() }, 1000)
onBeforeUnmount(() => window.clearInterval(timer))

const used = computed(() => props.startedAt
  ? Math.max(0, Math.round(((props.completedAt ? Date.parse(props.completedAt) : now.value) - Date.parse(props.startedAt)) / 1000))
  : 0)
const remaining = computed(() => Math.max(0, props.maxSeconds - used.value))
const progress = computed(() => Math.min(100, (used.value / props.maxSeconds) * 100))
</script>

<template>
  <div class="budget-meter">
    <div><span><i /> 全局 Watchdog</span><strong>{{ remaining }}<small>s</small></strong></div>
    <div class="budget-track"><i :style="{ width: `${progress}%` }" /></div>
    <small>600 秒预算 · 已用 {{ used }} 秒</small>
  </div>
</template>
