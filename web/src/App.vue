<script setup lang="ts">
import { Activity, BarChart3, GitPullRequest, ShieldCheck } from 'lucide-vue-next'
import {
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  darkTheme,
  type GlobalThemeOverrides,
} from 'naive-ui'

import { uiTokens } from '@/theme'

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: uiTokens.cyan,
    primaryColorHover: uiTokens.blue,
    primaryColorPressed: uiTokens.cyan,
    bodyColor: uiTokens.bg,
    cardColor: uiTokens.surface,
    modalColor: uiTokens.surfaceRaised,
    popoverColor: uiTokens.surfaceRaised,
    borderColor: uiTokens.border,
    textColorBase: uiTokens.text,
    textColor2: uiTokens.muted,
    borderRadius: '6px',
  },
}
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="themeOverrides">
    <NDialogProvider>
      <NMessageProvider>
        <div class="app-shell">
          <header class="topbar">
            <RouterLink class="brand" to="/review" aria-label="ReviewCrew 审查驾驶舱">
              <span class="brand-mark"><ShieldCheck :size="19" /></span>
              <span>ReviewCrew</span>
            </RouterLink>
            <nav class="nav" aria-label="主导航">
              <RouterLink to="/review">
                <GitPullRequest :size="16" />
                审查
              </RouterLink>
              <RouterLink to="/benchmark">
                <BarChart3 :size="16" />
                Benchmark
              </RouterLink>
            </nav>
            <div class="system-state" title="后端 API 已连接">
              <i /><Activity :size="13" /> API CONNECTED
            </div>
          </header>
          <main><RouterView /></main>
        </div>
      </NMessageProvider>
    </NDialogProvider>
  </NConfigProvider>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.topbar {
  align-items: center;
  background: color-mix(in srgb, var(--color-bg) 94%, var(--color-surface));
  border-bottom: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: 14rem 1fr auto;
  height: var(--app-bar-height);
  padding: 0 var(--space-4);
  position: sticky;
  top: 0;
  z-index: 50;
}

.brand,
.nav a,
.system-state {
  align-items: center;
  display: inline-flex;
  gap: var(--space-2);
}

.brand {
  color: var(--color-text);
  font-size: 0.9rem;
  font-weight: 600;
  text-decoration: none;
}

.brand-mark {
  align-items: center;
  background: var(--color-cyan);
  border-radius: var(--radius-md);
  color: var(--color-bg);
  display: inline-flex;
  height: 1.9rem;
  justify-content: center;
  width: 1.9rem;
}

.nav {
  display: flex;
  gap: var(--space-1);
  height: 100%;
}

.nav a {
  align-self: center;
  border-radius: var(--radius-md);
  color: var(--color-muted);
  font-size: 0.76rem;
  font-weight: 500;
  padding: var(--space-2) var(--space-3);
  text-decoration: none;
}

.nav a:hover,
.nav a.router-link-active {
  background: var(--color-surface-raised);
  color: var(--color-text);
}

.nav a.router-link-active {
  box-shadow: inset 0 -2px var(--color-cyan);
}

.system-state {
  background: color-mix(in srgb, var(--color-green) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-green) 22%, var(--color-border));
  border-radius: var(--radius-sm);
  color: var(--color-green);
  font-family: var(--font-mono);
  font-size: 0.62rem;
  gap: var(--space-1);
  justify-self: end;
  padding: var(--space-1) var(--space-2);
  text-transform: uppercase;
}

.system-state i {
  animation: pulse-opacity 1.5s infinite;
  background: var(--color-green);
  border-radius: 50%;
  height: 0.4rem;
  width: 0.4rem;
}
</style>
