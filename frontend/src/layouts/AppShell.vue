<script setup lang="ts">
import { ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { clearTokens, isLoggedIn } from '../lib/auth'

const route = useRoute()
const router = useRouter()
const logged = ref(isLoggedIn())

watch(
  () => route.fullPath,
  () => {
    logged.value = isLoggedIn()
  }
)

function logout() {
  clearTokens()
  logged.value = false
  router.push({ name: 'home' })
}
</script>

<template>
  <div class="shell">
    <header class="shell__header">
      <div class="shell__inner shell__bar">
        <RouterLink to="/" class="shell__brand">
          <span class="shell__logo" aria-hidden="true" />
          <span class="shell__title">Voice Redact</span>
        </RouterLink>
        <nav class="shell__nav" aria-label="Основная навигация">
          <RouterLink to="/" class="shell__link" active-class="shell__link--active">Главная</RouterLink>
          <RouterLink to="/demo" class="shell__link" active-class="shell__link--active">Пример экрана</RouterLink>
          <template v-if="logged">
            <RouterLink to="/upload" class="shell__link" active-class="shell__link--active">Загрузка</RouterLink>
            <button type="button" class="shell__link shell__link--btn" @click="logout">Выйти</button>
          </template>
          <template v-else>
            <RouterLink to="/login" class="shell__link" active-class="shell__link--active">Вход</RouterLink>
            <RouterLink to="/register" class="shell__link" active-class="shell__link--active">Регистрация</RouterLink>
          </template>
        </nav>
      </div>
    </header>

    <main class="shell__main">
      <div class="shell__inner">
        <RouterView />
      </div>
    </main>

    <footer class="shell__footer">
      <div class="shell__inner shell__footer-inner">
        <span>Защита персональных данных в голосовых записях</span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100svh;
  display: flex;
  flex-direction: column;
}

.shell__inner {
  width: 100%;
  max-width: var(--max-w);
  margin: 0 auto;
  padding: 0 1.25rem;
}

.shell__header {
  position: sticky;
  top: 0;
  z-index: 20;
  height: var(--nav-h);
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-elevated) 92%, transparent);
  backdrop-filter: blur(10px);
}

.shell__bar {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.shell__brand {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  color: var(--text-strong);
  text-decoration: none;
  font-weight: 600;
  letter-spacing: -0.03em;
}

.shell__brand:hover {
  text-decoration: none;
  color: var(--accent);
}

.shell__logo {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--accent) 0%, #a855f7 100%);
  box-shadow: var(--shadow-sm);
}

.shell__title {
  font-size: 1.05rem;
}

.shell__nav {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.shell__link {
  padding: 0.45rem 0.75rem;
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 0.9rem;
  font-weight: 500;
  text-decoration: none;
  transition:
    background 0.15s,
    color 0.15s;
}

.shell__link:hover {
  color: var(--text-strong);
  background: var(--bg-muted);
  text-decoration: none;
}

.shell__link.router-link-active,
.shell__link--active {
  color: var(--accent);
  background: var(--accent-soft);
}

.shell__link--btn {
  border: none;
  background: transparent;
  cursor: pointer;
  font: inherit;
}

.shell__link--btn:hover {
  background: var(--bg-muted);
}

.shell__main {
  flex: 1;
  padding: 2rem 0 3rem;
}

.shell__footer {
  border-top: 1px solid var(--border);
  padding: 1rem 0;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.shell__footer-inner {
  text-align: center;
  opacity: 0.9;
}
</style>
