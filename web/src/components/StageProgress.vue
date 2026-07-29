<template>
  <div class="stage-progress">
    <div class="progress-bar-bg">
      <div class="progress-bar-fill" :style="{ width: progress.percent + '%' }"></div>
    </div>
    <div class="stage-dots">
      <div
        v-for="(stage, idx) in stages"
        :key="stage.key"
        class="stage-dot-wrap"
        :class="{
          active: stage.status === 'running',
          done: stage.status === 'completed',
          failed: stage.status === 'failed',
          current: idx === progress.runningIndex,
        }"
      >
        <div class="stage-dot">
          <span v-if="stage.status === 'completed'" class="checkmark">&#10003;</span>
          <span v-else-if="stage.status === 'failed'" class="cross">&#10007;</span>
          <span v-else-if="stage.status === 'running'" class="dot-inner"></span>
        </div>
        <span class="stage-label">{{ stage.name }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { StageInfo } from '../stores/review'

defineProps<{
  stages: StageInfo[]
  progress: { completed: number; total: number; percent: number; runningIndex: number }
}>()
</script>

<style scoped>
.stage-progress {
  margin-bottom: 24px;
}

.progress-bar-bg {
  height: 6px;
  background: var(--color-border);
  border-radius: 3px;
  margin-bottom: 12px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: var(--color-primary);
  border-radius: 3px;
  transition: width 0.4s ease;
}

.stage-dots {
  display: flex;
  justify-content: space-between;
}

.stage-dot-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  flex: 1;
  position: relative;
}

.stage-dot-wrap::after {
  content: '';
  position: absolute;
  top: 14px;
  left: 50%;
  width: 100%;
  height: 2px;
  background: var(--color-border);
  z-index: 0;
}

.stage-dot-wrap:last-child::after {
  display: none;
}

.stage-dot-wrap.done::after {
  background: var(--color-primary);
}

.stage-dot-wrap.active::after {
  background: linear-gradient(to right, var(--color-primary), var(--color-border));
}

.stage-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  position: relative;
  z-index: 1;
  transition: all 0.3s;
}

.stage-dot-wrap.done .stage-dot {
  background: var(--color-success);
  color: #fff;
  transition: background 0.3s ease;
}

.stage-dot-wrap.active .stage-dot {
  background: var(--color-primary);
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.2);
  transition: background 0.3s ease, box-shadow 0.3s ease;
}

.stage-dot-wrap.failed .stage-dot {
  background: var(--color-danger);
  color: #fff;
  transition: background 0.3s ease;
}

.dot-inner {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #fff;
  animation: pulse-dot 1s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.checkmark {
  color: #fff;
  font-size: 14px;
}

.cross {
  color: #fff;
  font-size: 14px;
}

.stage-label {
  font-size: 11px;
  color: var(--color-text-muted);
  white-space: nowrap;
  text-align: center;
  transition: color 0.3s ease, font-weight 0.3s ease;
}

.stage-dot-wrap.active .stage-label {
  color: var(--color-primary);
  font-weight: 600;
}

.stage-dot-wrap.done .stage-label {
  color: var(--color-success);
}
</style>
