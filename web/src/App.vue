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
            <div class="system-state">
              <Activity :size="14" /> API
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
  background: color-mix(in srgb, var(--color-bg) 92%, transparent);
  border-bottom: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: minmax(11rem, 1fr) auto minmax(11rem, 1fr);
  height: 3.5rem;
  padding: 0 var(--space-5);
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
  font-size: 0.96rem;
  font-weight: 700;
  text-decoration: none;
}

.brand-mark {
  align-items: center;
  background: var(--color-cyan);
  border-radius: var(--radius-md);
  color: var(--color-bg);
  display: inline-flex;
  height: 1.85rem;
  justify-content: center;
  width: 1.85rem;
}

.nav {
  display: flex;
  gap: var(--space-1);
}

.nav a {
  border-radius: var(--radius-md);
  color: var(--color-muted);
  padding: var(--space-2) var(--space-3);
  text-decoration: none;
}

.nav a:hover,
.nav a.router-link-active {
  background: var(--color-surface-raised);
  color: var(--color-text);
}

.system-state {
  color: var(--color-green);
  font-family: var(--font-mono);
  font-size: 0.72rem;
  justify-self: end;
  text-transform: uppercase;
}

@media (max-width: 680px) {
  .topbar {
    grid-template-columns: 1fr auto;
    padding: 0 var(--space-3);
  }

  .brand > span:last-child,
  .system-state,
  .nav a {
    font-size: 0;
  }

  .nav a svg {
    height: 1.1rem;
    width: 1.1rem;
  }
}
</style>
