<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { clearTokens, isLoggedIn } from '../lib/auth'

const route = useRoute()
const router = useRouter()
const logged = ref(isLoggedIn())
const menuOpen = ref(false)

watch(
  () => route.fullPath,
  () => {
    logged.value = isLoggedIn()
    menuOpen.value = false
  }
)

watch(menuOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})

function onDocumentKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') menuOpen.value = false
}

onMounted(() => {
  document.addEventListener('keydown', onDocumentKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onDocumentKeydown)
  document.body.style.overflow = ''
})

function toggleMenu() {
  menuOpen.value = !menuOpen.value
}

function logout() {
  clearTokens()
  logged.value = false
  menuOpen.value = false
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
        <button
          type="button"
          class="shell__menu-btn"
          :aria-expanded="menuOpen"
          aria-controls="primary-nav"
          :aria-label="menuOpen ? 'Закрыть меню' : 'Открыть меню'"
          @click="toggleMenu"
        >
          <span class="shell__menu-icon" aria-hidden="true">
            <span class="shell__menu-line" />
            <span class="shell__menu-line" />
            <span class="shell__menu-line" />
          </span>
        </button>
        <div
          class="shell__backdrop"
          :class="{ 'shell__backdrop--visible': menuOpen }"
          aria-hidden="true"
          @click="menuOpen = false"
        />
        <nav
          id="primary-nav"
          class="shell__nav"
          :class="{ 'shell__nav--open': menuOpen }"
          aria-label="Основная навигация"
        >
          <RouterLink to="/" class="shell__link" active-class="shell__link--active" @click="menuOpen = false"
            >Главная</RouterLink
          >
          <template v-if="logged">
            <RouterLink
              to="/upload"
              class="shell__link"
              active-class="shell__link--active"
              @click="menuOpen = false"
              >Загрузка</RouterLink
            >
            <RouterLink
              to="/history"
              class="shell__link"
              active-class="shell__link--active"
              @click="menuOpen = false"
              >История</RouterLink
            >
            <button type="button" class="shell__link shell__link--btn" @click="logout">Выйти</button>
          </template>
          <template v-else>
            <RouterLink to="/login" class="shell__link" active-class="shell__link--active" @click="menuOpen = false"
              >Вход</RouterLink
            >
            <RouterLink
              to="/register"
              class="shell__link"
              active-class="shell__link--active"
              @click="menuOpen = false"
              >Регистрация</RouterLink
            >
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
  gap: 0.75rem;
  position: relative;
  z-index: 1;
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
  background: linear-gradient(145deg, var(--accent) 0%, color-mix(in srgb, var(--accent) 55%, #38bdf8) 100%);
  box-shadow: var(--shadow-sm);
}

.shell__title {
  font-size: 1.05rem;
}

.shell__menu-btn {
  display: none;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-muted);
  color: var(--text-strong);
  cursor: pointer;
  transition:
    background 0.15s,
    border-color 0.15s;
}

.shell__menu-btn:hover {
  background: var(--bg);
  border-color: var(--border-strong);
}

.shell__menu-icon {
  display: flex;
  width: 1.15rem;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
}

.shell__menu-line {
  display: block;
  height: 2px;
  border-radius: 1px;
  background: currentColor;
  transition:
    transform 0.2s ease,
    opacity 0.2s ease;
}

.shell__menu-btn[aria-expanded='true'] .shell__menu-line:nth-child(1) {
  transform: translateY(7px) rotate(45deg);
}

.shell__menu-btn[aria-expanded='true'] .shell__menu-line:nth-child(2) {
  opacity: 0;
}

.shell__menu-btn[aria-expanded='true'] .shell__menu-line:nth-child(3) {
  transform: translateY(-7px) rotate(-45deg);
}

.shell__backdrop {
  display: none;
}

.shell__nav {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-wrap: nowrap;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .shell__menu-btn {
    display: inline-flex;
  }

  .shell__backdrop {
    display: block;
    position: fixed;
    top: var(--nav-h);
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 0;
    margin: 0;
    padding: 0;
    border: none;
    background: rgba(0, 0, 0, 0.48);
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
    transition:
      opacity 0.2s ease,
      visibility 0.2s ease;
  }

  .shell__backdrop--visible {
    opacity: 1;
    visibility: visible;
    pointer-events: auto;
  }

  .shell__nav {
    position: fixed;
    top: var(--nav-h);
    left: 0;
    right: 0;
    z-index: 1;
    flex-direction: column;
    align-items: stretch;
    gap: 0.35rem;
    max-height: min(70vh, calc(100svh - var(--nav-h)));
    margin: 0;
    padding: 0.75rem 1.25rem 1rem;
    border-bottom: 1px solid var(--border);
    background: var(--bg-elevated);
    box-shadow: var(--shadow-md);
    overflow-y: auto;
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
    transform: translateY(-0.5rem);
    transition:
      opacity 0.2s ease,
      visibility 0.2s ease,
      transform 0.2s ease;
  }

  .shell__nav--open {
    opacity: 1;
    visibility: visible;
    pointer-events: auto;
    transform: translateY(0);
  }

  .shell__link {
    text-align: left;
    width: 100%;
    box-sizing: border-box;
  }
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
