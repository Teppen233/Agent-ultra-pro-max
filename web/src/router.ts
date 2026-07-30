import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', redirect: '/review' },
    {
      path: '/review/:runId?',
      name: 'review',
      component: () => import('@/views/ReviewView.vue'),
    },
    {
      path: '/review/:runId/diff',
      name: 'diff',
      component: () => import('@/views/DiffView.vue'),
    },
    {
      path: '/review/:runId/report',
      name: 'report',
      component: () => import('@/views/ReportView.vue'),
    },
    {
      path: '/benchmark',
      name: 'benchmark',
      component: () => import('@/views/BenchmarkView.vue'),
    },
  ],
})
