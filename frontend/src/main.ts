import '@fontsource-variable/manrope'
import '@fontsource-variable/noto-sans-sc'
import './styles.css'

import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'

createApp(App).use(createPinia()).use(router).mount('#app')
