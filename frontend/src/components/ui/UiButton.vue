<script setup lang="ts">
import { RouterLink } from 'vue-router'

defineProps<{
  variant?: 'primary' | 'secondary' | 'ghost'
  block?: boolean
  /** Если задан — рендерится как RouterLink */
  to?: string
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

.btn:hover {
  background: var(--accent-hover);
  text-decoration: none;
}

.btn:focus-visible {
  outline: 2px solid var(--accent-ring);
  outline-offset: 2px;
}

.btn:active {
  transform: translateY(1px);
}

.btn--secondary {
  color: var(--text-strong);
  background: var(--bg-elevated);
  border-color: var(--border);
  box-shadow: none;
}

.btn--secondary:hover {
  background: var(--bg-muted);
}

.btn--ghost {
  color: var(--accent);
  background: transparent;
  box-shadow: none;
}

.btn--ghost:hover {
  background: var(--accent-soft);
}

.btn--block {
  width: 100%;
}
</style>
