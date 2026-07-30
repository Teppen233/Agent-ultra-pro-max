<script setup lang="ts">
import { BaseEdge, type EdgeProps } from '@vue-flow/core'

interface WorkflowEdgeData {
  path: string
}

const props = defineProps<EdgeProps<WorkflowEdgeData>>()
</script>

<template>
  <BaseEdge
    :id="props.id"
    :path="props.data.path"
    :marker-start="props.markerStart"
    :marker-end="props.markerEnd"
    :interaction-width="props.interactionWidth ?? 20"
    :style="props.style"
  />
</template>
