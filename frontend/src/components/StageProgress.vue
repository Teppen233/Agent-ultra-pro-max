<script setup lang="ts">
import type { StageState } from '@/contracts'

defineProps<{ stages: StageState[] }>()
</script>

<template>
  <ol class="stage-progress" aria-label="审查阶段">
    <li v-for="(stage, index) in stages" :key="stage.id" :class="stage.status">
      <span class="stage-index">
        <svg v-if="stage.status === 'completed'" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 12 4 4 8-9" /></svg>
        <b v-else>{{ index + 1 }}</b>
      </span>
      <span class="stage-copy"><small>阶段 {{ String(index + 1).padStart(2, '0') }}</small><strong>{{ stage.label }}</strong></span>
      <i v-if="index < stages.length - 1" />
    </li>
  </ol>
</template>
