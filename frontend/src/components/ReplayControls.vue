<script setup lang="ts">
import { supportedReplaySpeeds } from '@/api/client'

const props = defineProps<{
  speed: number
  paused: boolean
  skipIdle: boolean
  originalElapsedMs: number
  replayElapsedMs: number
}>()

const emit = defineEmits<{
  'update:speed': [speed: number]
  'update:paused': [paused: boolean]
  'update:skipIdle': [skipIdle: boolean]
  restart: []
}>()

/** 将毫秒时长显示为易于比较的中文秒数。 */
const presentElapsed = (milliseconds: number): string => `${(Math.max(0, milliseconds) / 1_000).toFixed(1)} 秒`
</script>

<template>
  <section class="replay-controls panel" aria-label="回放控制">
    <div><span class="eyebrow">回放控制</span><strong>原始运行 {{ presentElapsed(props.originalElapsedMs) }}</strong><small>当前回放 {{ presentElapsed(props.replayElapsedMs) }}</small></div>
    <div class="replay-control-actions">
      <button v-for="item in supportedReplaySpeeds" :key="item" type="button" :class="{ active: props.speed === item }" @click="emit('update:speed', item)">{{ item }}×</button>
      <button type="button" @click="emit('update:paused', !props.paused)">{{ props.paused ? '继续播放' : '暂停播放' }}</button>
      <button type="button" @click="emit('restart')">重新开始</button>
      <label><input type="checkbox" :checked="props.skipIdle" @change="emit('update:skipIdle', ($event.target as HTMLInputElement).checked)"> 跳过空闲时间</label>
    </div>
  </section>
</template>

<style scoped>
.replay-controls { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin: 16px 0; padding: 14px 16px; }
.replay-controls > div:first-child { display: flex; flex-direction: column; gap: 3px; }.replay-controls strong { color: #dbeaf4; font-size: 11px; }.replay-controls small { color: #6d869a; font-size: 9px; }
.replay-control-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 6px; }.replay-control-actions button { border: 1px solid #2c4a60; border-radius: 4px; background: #10253a; color: #a8bdcc; padding: 5px 8px; font-size: 9px; }.replay-control-actions button.active, .replay-control-actions button:hover { border-color: var(--cyan); color: var(--cyan); }.replay-control-actions label { color: #8298aa; font-size: 9px; }
@media (max-width: 760px) { .replay-controls { align-items: flex-start; flex-direction: column; }.replay-control-actions { justify-content: flex-start; } }
</style>
