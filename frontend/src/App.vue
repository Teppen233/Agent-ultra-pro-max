<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="ReviewCrew 首页">
        <span class="brand-mark"><i /><i /><i /></span>
        <span>
          <strong>ReviewCrew</strong>
          <small>AI CODE REVIEW TEAM</small>
        </span>
      </RouterLink>
      <nav aria-label="主导航">
        <RouterLink to="/" :class="{ active: route.name === 'start' }">新建审查</RouterLink>
        <RouterLink to="/history" :class="{ active: route.name === 'history' }">历史与回放</RouterLink>
      </nav>
      <div class="system-status"><span /> 系统就绪</div>
    </header>
    <main>
      <RouterView />
    </main>
  </div>
</template>
