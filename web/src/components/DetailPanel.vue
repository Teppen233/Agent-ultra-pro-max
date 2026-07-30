<template>
  <Teleport to="body">
    <div v-if="visible" class="panel-overlay" @click.self="$emit('close')">
      <div class="detail-panel" :class="{ open: visible }">
        <div class="panel-header">
          <h3>{{ title }}</h3>
          <button class="panel-close" @click="$emit('close')">&times;</button>
        </div>

        <div class="panel-body">
          <p v-if="!findings.length" class="empty">暂无审查发现</p>

          <FindingCard
            v-for="entry in findings"
            :key="entry.finding.id"
            :finding="entry.finding"
            :verifier-status="entry.verifierStatus"
            :verifier-reason="entry.verifierReason"
            :show-detail="true"
          />
        </div>

        <div class="panel-footer">
          <span class="count">{{ findings.length }} 个发现</span>
          <button class="btn-close" @click="$emit('close')">关闭</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import FindingCard from './FindingCard.vue'

defineProps<{
  visible: boolean
  title: string
  findings: Array<{
    finding: any
    verifierStatus: string
    verifierReason?: string
  }>
}>()

defineEmits<{ close: [] }>()
</script>

<style scoped>
.panel-overlay {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0,0,0,0.2);
  display: flex;
  justify-content: flex-end;
}

.detail-panel {
  width: 480px;
  max-width: 90vw;
  height: 100vh;
  background: var(--color-surface);
  box-shadow: -4px 0 24px rgba(0,0,0,0.12);
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.25s ease;
}

.detail-panel.open {
  transform: translateX(0);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.panel-header h3 {
  font-size: 16px;
  font-weight: 600;
}

.panel-close {
  width: 28px; height: 28px;
  border: none; background: none;
  font-size: 20px; cursor: pointer;
  color: var(--color-text-muted);
  border-radius: 4px;
}

.panel-close:hover { background: var(--color-bg); }

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.empty {
  color: var(--color-text-muted);
  text-align: center;
  padding: 48px 0;
}

.panel-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-top: 1px solid var(--color-border);
  flex-shrink: 0;
}

.count {
  font-size: 13px;
  color: var(--color-text-muted);
}

.btn-close {
  padding: 6px 20px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}
</style>
