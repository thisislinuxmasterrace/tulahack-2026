<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import PageIntro from '../components/ui/PageIntro.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import { registerRequest, setTokens } from '../lib/auth'

const router = useRouter()

const username = ref('')
const password = ref('')
const password2 = ref('')
const err = ref('')
const loading = ref(false)

async function submit() {
  err.value = ''
  if (password.value !== password2.value) {
    err.value = 'Пароли не совпадают'
    return
  }
  loading.value = true
  try {
    const data = await registerRequest(username.value.trim(), password.value)
    setTokens(data.access_token, data.refresh_token)
    await router.replace('/upload')
  } catch (e) {
    err.value = e instanceof Error ? e.message : 'Ошибка регистрации'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth">
    <PageIntro title="Регистрация" subtitle="Придумайте логин и пароль (не короче 8 символов)." />

    <UiCard title="Новый аккаунт">
      <form class="auth__form" @submit.prevent="submit">
        <label class="auth__field">
          <span class="auth__label">Логин</span>
          <input v-model="username" class="auth__input" type="text" autocomplete="username" required />
        </label>
        <label class="auth__field">
          <span class="auth__label">Пароль</span>
          <input
            v-model="password"
            class="auth__input"
            type="password"
            autocomplete="new-password"
            required
            minlength="8"
          />
        </label>
        <label class="auth__field">
          <span class="auth__label">Пароль ещё раз</span>
          <input
            v-model="password2"
            class="auth__input"
            type="password"
            autocomplete="new-password"
            required
            minlength="8"
          />
        </label>
        <p v-if="err" class="auth__err" role="alert">{{ err }}</p>
        <UiButton type="submit" variant="primary" block :disabled="loading">
          {{ loading ? '…' : 'Зарегистрироваться' }}
        </UiButton>
        <p class="auth__hint">
          Уже есть аккаунт?
          <RouterLink to="/login">Войти</RouterLink>
        </p>
      </form>
    </UiCard>
  </div>
</template>

<style scoped>
.auth__form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.auth__field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.auth__label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-muted);
}

.auth__input {
  padding: 0.55rem 0.75rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-strong);
  font-size: 0.95rem;
}

.auth__input:focus {
  outline: 2px solid var(--accent-ring);
  border-color: var(--accent);
}

.auth__err {
  margin: 0;
  font-size: 0.88rem;
  color: #dc2626;
}

.auth__hint {
  margin: 0;
  font-size: 0.88rem;
  color: var(--text-muted);
  text-align: center;
}

.auth__hint a {
  color: var(--accent);
  font-weight: 600;
  text-decoration: none;
}

.auth__hint a:hover {
  text-decoration: underline;
}
</style>
