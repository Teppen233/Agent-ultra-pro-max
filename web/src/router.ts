import { createRouter, createWebHashHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'start',
      component: () => import('./pages/StartPage.vue'),
    },
    {
      path: '/review/:runId',
      name: 'review',
      component: () => import('./pages/ReviewPage.vue'),
    },
    {
      path: '/result/:runId',
      name: 'result',
      component: () => import('./pages/ResultPage.vue'),
    },
    {
      path: '/benchmark',
      name: 'benchmark',
      component: () => import('./pages/BenchmarkPage.vue'),
    },
  ],
})
