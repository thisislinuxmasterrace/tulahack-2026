import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '../views/HomeView.vue'
import UploadView from '../views/UploadView.vue'
import ResultDemoView from '../views/ResultDemoView.vue'
import ResultView from '../views/ResultView.vue'
import HistoryView from '../views/HistoryView.vue'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import { getAccessToken } from '../lib/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: HomeView, meta: { title: 'Главная' } },
    { path: '/login', name: 'login', component: LoginView, meta: { title: 'Вход', requiresGuest: true } },
    {
      path: '/register',
      name: 'register',
      component: RegisterView,
      meta: { title: 'Регистрация', requiresGuest: true },
    },
    {
      path: '/upload',
      name: 'upload',
      component: UploadView,
      meta: { title: 'Загрузка', requiresAuth: true },
    },
    {
      path: '/history',
      name: 'history',
      component: HistoryView,
      meta: { title: 'История обработок', requiresAuth: true },
    },
    { path: '/demo', name: 'demo', component: ResultDemoView, meta: { title: 'Пример экрана' } },
    {
      path: '/result/:uploadId',
      name: 'result',
      component: ResultView,
      meta: { title: 'Результат', requiresAuth: true },
    },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to) => {
  const token = getAccessToken()
  if (to.meta.requiresAuth && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresGuest && token) {
    return { name: 'upload' }
  }
  return true
})

router.afterEach((to) => {
  const base = 'Анонимизация голосовых данных'
  document.title = to.meta.title ? `${to.meta.title as string} · ${base}` : base
})

export default router
