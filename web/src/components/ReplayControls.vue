<script setup lang="ts">
import { Pause, Play, RotateCcw, SkipBack, SkipForward } from 'lucide-vue-next'
import {
  NButton,
  NButtonGroup,
  NRadioButton,
  NRadioGroup,
  NSlider,
  NTooltip,
} from 'naive-ui'
import { computed } from 'vue'

import type { ReplaySpeed } from '@/stores/review'

const props = defineProps<{
  index: number
  total: number
  playing: boolean
  speed: ReplaySpeed
  live: boolean
}>()
const emit = defineEmits<{
  restart: []
  previous: []
  toggle: []
  next: []
  seek: [index: number]
  speed: [speed: ReplaySpeed]
}>()

const speeds: ReplaySpeed[] = [0.5, 1, 2, 4]
const disabled = computed(() => props.live || props.total === 0)

function updateSpeed(value: string | number | boolean) {
  if (typeof value === 'number' && speeds.includes(value as ReplaySpeed)) {
    emit('speed', value as ReplaySpeed)
  }
}
</script>

<template>
  <section class="replay-controls" aria-label="任务回放控制">
    <div class="replay-actions">
      <NButtonGroup size="small">
        <NTooltip>
          <template #trigger>
            <NButton
              data-testid="replay-restart"
              :disabled="disabled"
              aria-label="重新播放"
              @click="emit('restart')"
            >
              <template #icon>
                <RotateCcw :size="15" />
              </template>
            </NButton>
          </template>
          重新播放
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton
              data-testid="replay-previous"
              :disabled="disabled || index <= 0"
              aria-label="上一步"
              @click="emit('previous')"
            >
              <template #icon>
                <SkipBack :size="15" />
              </template>
            </NButton>
          </template>
          上一步
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton
              data-testid="replay-toggle"
              :disabled="disabled"
              type="primary"
              aria-label="播放或暂停"
              @click="emit('toggle')"
            >
              <template #icon>
                <Pause v-if="playing" :size="15" />
                <Play v-else :size="15" />
              </template>
            </NButton>
          </template>
          {{ playing ? '暂停' : '播放' }}
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton
              data-testid="replay-next"
              :disabled="disabled || index >= total"
              aria-label="下一步"
              @click="emit('next')"
            >
              <template #icon>
                <SkipForward :size="15" />
              </template>
            </NButton>
          </template>
          下一步
        </NTooltip>
      </NButtonGroup>
      <span v-if="live" class="live-copy">实时追踪</span>
      <span v-else class="progress-copy">事件 {{ index }} / {{ total }}</span>
    </div>

    <NSlider
      class="replay-slider"
      :value="index"
      :min="0"
      :max="Math.max(total, 1)"
      :step="1"
      :disabled="disabled"
      :tooltip="false"
      aria-label="回放进度"
      @update:value="emit('seek', $event)"
    />

    <NRadioGroup
      :value="speed"
      size="small"
      :disabled="live"
      aria-label="回放速度"
      @update:value="updateSpeed"
    >
      <NRadioButton v-for="option in speeds" :key="option" :value="option">
        {{ option }}x
      </NRadioButton>
    </NRadioGroup>
  </section>
</template>

<style scoped>
.replay-controls {
  background: color-mix(in srgb, var(--color-surface) 86%, var(--color-bg));
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: grid;
  gap: var(--space-3);
  grid-template-columns: auto minmax(8rem, 1fr) auto;
  min-height: 3.1rem;
  padding: var(--space-2) var(--space-4);
}

.replay-actions {
  align-items: center;
  display: flex;
  gap: var(--space-3);
}

.progress-copy,
.live-copy {
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 0.66rem;
  white-space: nowrap;
}

.live-copy {
  color: var(--color-green);
}

.replay-slider {
  min-width: 8rem;
}

</style>
