<script setup lang="ts">
import { RouterLink } from 'vue-router'

defineProps<{
  variant?: 'primary' | 'secondary' | 'ghost'
  block?: boolean
  to?: string
  /** Не используется для ссылки (`to`). */
  disabled?: boolean
}>()
</script>

<template>
  <component
    :is="to ? RouterLink : 'button'"
    :to="to"
    class="btn"
    :class="[
      variant === 'secondary' && 'btn--secondary',
      variant === 'ghost' && 'btn--ghost',
      block && 'btn--block',
    ]"
    :disabled="to ? undefined : disabled"
  >
    <slot />
  </component>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  padding: 0.55rem 1.1rem;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 0.92rem;
  font-weight: 600;
  cursor: pointer;
  color: #fff;
  background: var(--accent);
  box-shadow: var(--shadow-sm);
  text-decoration: none;
  transition:
    background 0.15s,
    transform 0.1s;
}

.btn:hover:not(:disabled) {
  background: var(--accent-hover);
  text-decoration: none;
}

.btn:focus-visible {
  outline: 2px solid var(--accent-ring);
  outline-offset: 2px;
}

.btn:active:not(:disabled) {
  transform: translateY(1px);
}

.btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
  box-shadow: none;
  color: var(--text-muted);
  background: var(--bg-muted);
  border-color: var(--border);
  transform: none;
}

.btn:disabled:hover {
  background: var(--bg-muted);
}

.btn--secondary {
  color: var(--text-strong);
  background: var(--bg-elevated);
  border-color: var(--border);
  box-shadow: none;
}

.btn--secondary:hover:not(:disabled) {
  background: var(--bg-muted);
}

.btn--ghost {
  color: var(--accent);
  background: transparent;
  box-shadow: none;
}

.btn--ghost:hover:not(:disabled) {
  background: var(--accent-soft);
}

.btn--secondary:disabled,
.btn--ghost:disabled {
  color: var(--text-muted);
  background: var(--bg-muted);
  border-color: var(--border);
  opacity: 0.55;
}

.btn--ghost:disabled {
  background: transparent;
  border-color: transparent;
}

.btn--block {
  width: 100%;
}
</style>
