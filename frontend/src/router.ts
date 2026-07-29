import { createRouter, createWebHistory } from 'vue-router'

import HistoryPage from '@/pages/HistoryPage.vue'
import ResultPage from '@/pages/ResultPage.vue'
import ReviewPage from '@/pages/ReviewPage.vue'
import StartPage from '@/pages/StartPage.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'start', component: StartPage },
    { path: '/review/:runId', name: 'review', component: ReviewPage },
    { path: '/result/:runId', name: 'result', component: ResultPage },
    { path: '/history', name: 'history', component: HistoryPage },
  ],
})
