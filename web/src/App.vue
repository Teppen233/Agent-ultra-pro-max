<template>
  <div class="app-container">
    <header class="app-header">
      <h1
        class="app-logo"
        role="button"
        tabindex="0"
        @click="$router.push('/')"
        @keydown.enter="$router.push('/')"
        @keydown.space.prevent="$router.push('/')"
      >ReviewCrew</h1>
      <nav class="app-nav">
        <router-link to="/" class="nav-link">启动审查</router-link>
        <router-link to="/benchmark" class="nav-link">评测</router-link>
      </nav>
    </header>
    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup lang="ts">
// 根组件 —— 提供全局导航
</script>

<style>
/* 全局重置 */
*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --color-bg: #f5f7fa;
  --color-surface: #ffffff;
  --color-border: #e2e8f0;
  --color-text: #1a202c;
  --color-text-muted: #718096;
  --color-primary: #3b82f6;
  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-danger: #ef4444;
  --color-info: #6366f1;
  --radius: 8px;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    sans-serif;
  background: var(--color-bg);
  color: var(--color-text);
  line-height: 1.6;
}

.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  padding: 0 24px;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 32px;
  box-shadow: var(--shadow);
  position: sticky;
  top: 0;
  z-index: 100;
}

.app-logo {
  font-size: 20px;
  font-weight: 700;
  color: var(--color-primary);
  cursor: pointer;
  user-select: none;
  outline: none;
  border-radius: 4px;
  padding: 4px 8px;
  margin: -4px -8px;
}

.app-logo:focus-visible {
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.4);
}

.app-nav {
  display: flex;
  gap: 16px;
}

.nav-link {
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 4px;
  transition: color 0.15s, background 0.15s;
  outline: none;
}

.nav-link:hover {
  color: var(--color-primary);
  background: rgba(59, 130, 246, 0.06);
}

.nav-link:focus-visible {
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.4);
}

.nav-link.router-link-exact-active {
  color: var(--color-primary);
}

.app-main {
  flex: 1;
  padding: 24px;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
}

/* 页面过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* 全局焦点可见样式 */
:focus-visible {
  outline: none;
}

button:focus-visible,
a:focus-visible,
input:focus-visible,
select:focus-visible,
[role="button"]:focus-visible {
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.4);
}

/* 响应式 */
@media (max-width: 640px) {
  .app-header {
    padding: 0 12px;
    height: 48px;
    gap: 16px;
  }

  .app-logo {
    font-size: 16px;
  }

  .nav-link {
    font-size: 12px;
    padding: 2px 6px;
  }

  .app-main {
    padding: 12px;
  }
}
</style>
