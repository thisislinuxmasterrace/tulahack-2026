<script setup lang="ts">
defineProps<{
  title?: string
}>()
</script>

<template>
  <section class="ui-card">
    <h2 v-if="title" class="ui-card__title">{{ title }}</h2>
    <slot />
  </section>
</template>

<style>
.ui-card {
  box-sizing: border-box;
  min-width: 0;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 1.35rem 1.5rem;
}

.ui-card__title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-strong);
  letter-spacing: -0.02em;
  margin: 0 0 0.75rem;
  line-height: 1.3;
}
</style>
