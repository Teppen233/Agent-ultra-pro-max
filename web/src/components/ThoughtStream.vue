<script setup lang="ts">
import { ChevronDown, ChevronUp, Search, Terminal } from 'lucide-vue-next'
import { computed, nextTick, ref, watch } from 'vue'

import type { PipelineEvent } from '@/types'

const props = defineProps<{ events: PipelineEvent[]; expanded: boolean }>()
const emit = defineEmits<{ toggle: [] }>()
const stream = ref<HTMLElement | null>(null)
const visible = computed(() =>
  props.events.filter((event) => event.type === 'thought' || event.type === 'tool').slice(-30),
)

const agentNames = {
  coordinator: '协调器',
  defect: '缺陷专家',
  intent: '意图专家',
  verifier: 'Verifier',
} as const

watch(
  () => props.events.length,
  async () => {
    await nextTick()
    if (props.expanded && stream.value) stream.value.scrollTop = stream.value.scrollHeight
  },
)
</script>

<template>
  <section class="thoughts" :class="{ expanded }">
    <button class="thought-toggle" type="button" :aria-expanded="expanded" @click="emit('toggle')">
      <span><Terminal :size="14" /> Agent 实时事件 <b>{{ visible.length }}</b></span>
      <span v-if="!expanded" class="latest-event">{{ visible.length ? '查看最新推理与工具调用' : '等待 Agent 事件' }}</span>
      <ChevronDown v-if="expanded" :size="15" />
      <ChevronUp v-else :size="15" />
    </button>
    <div v-if="expanded" ref="stream" class="thought-list scrollbar" aria-live="polite">
      <div v-if="visible.length === 0" class="thought-empty">
        等待 Agent 推理或工具调用
      </div>
      <article v-for="(event, index) in visible" :key="`${event.timestamp}-${index}`" :class="event.type">
        <template v-if="event.type === 'tool'">
          <Search :size="14" />
          <div>
            <strong>{{ agentNames[event.agent] }} / {{ event.tool }}</strong>
            <code>{{ JSON.stringify(event.args ?? {}) }}</code>
          </div>
        </template>
        <template v-else-if="event.type === 'thought'">
          <span class="thought-agent">{{ agentNames[event.agent].slice(0, 1) }}</span>
          <p><b>{{ agentNames[event.agent] }}</b>{{ event.text }}</p>
        </template>
      </article>
    </div>
  </section>
</template>

<style scoped>
.thoughts {
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
  min-height: 2.65rem;
}

.thought-toggle {
  align-items: center;
  background: transparent;
  border: 0;
  color: var(--color-muted);
  cursor: pointer;
  display: flex;
  font-family: var(--font-mono);
  font-size: 0.69rem;
  gap: var(--space-2);
  height: 2.65rem;
  justify-content: space-between;
  padding: 0 var(--space-4);
  text-transform: uppercase;
  width: 100%;
}

.thought-toggle:hover {
  background: var(--color-surface-raised);
  color: var(--color-text);
}

.thought-toggle > span:first-child {
  align-items: center;
  display: flex;
  gap: var(--space-2);
}

.thought-toggle b {
  color: var(--color-cyan);
  font-weight: 500;
}

.latest-event {
  color: var(--color-subtle);
  font-family: var(--font-sans);
  font-size: 0.65rem;
  margin-left: auto;
  text-transform: none;
}

.thought-list {
  border-top: 1px solid var(--color-border);
  height: 13rem;
  overflow-y: auto;
  padding: var(--space-3) var(--space-4);
}

.thought-list article {
  align-items: flex-start;
  display: flex;
  font-size: 0.78rem;
  gap: var(--space-2);
  line-height: 1.55;
  margin-bottom: var(--space-3);
}

.thought-list article.tool {
  background: var(--color-surface-raised);
  border-left: 2px solid var(--color-blue);
  border-radius: var(--radius-sm);
  color: var(--color-blue);
  padding: var(--space-2);
}

.tool strong {
  display: block;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 600;
}

.tool code {
  color: var(--color-muted);
  display: block;
  font-family: var(--font-mono);
  font-size: 0.67rem;
  margin-top: var(--space-1);
  overflow-wrap: anywhere;
}

.thought-agent {
  align-items: center;
  background: var(--color-violet);
  border-radius: var(--radius-sm);
  color: var(--color-bg);
  display: inline-flex;
  flex: 0 0 auto;
  font-family: var(--font-mono);
  font-weight: 800;
  height: 1.25rem;
  justify-content: center;
  width: 1.25rem;
}

.thought-list p {
  color: var(--color-muted);
  margin: 0;
}

.thought-list p b {
  color: var(--color-text);
  display: block;
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: 500;
  margin-bottom: var(--space-1);
}

.thought-empty {
  color: var(--color-subtle);
  font-size: 0.78rem;
  padding: var(--space-6) 0;
  text-align: center;
}
</style>
