<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header class="intro">
    <h1>{{ title }}</h1>
    <p v-if="subtitle" class="intro__sub">{{ subtitle }}</p>
  </header>
</template>

<style scoped>
.intro {
  margin-bottom: 1.75rem;
  max-width: 42rem;
}

.intro__sub {
  margin-top: 0.35rem;
  color: var(--text-muted);
  font-size: 0.98rem;
  line-height: 1.55;
}
</style>
