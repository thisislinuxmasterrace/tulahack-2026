<script setup lang="ts">
import { computed, ref } from 'vue'

import type { ProcessingLogEntry } from '../../types/processingLog'

const props = defineProps<{
  entries: ProcessingLogEntry[]
}>()

const showRaw = ref(false)

const jsonPretty = computed(() => JSON.stringify(props.entries, null, 2))

function formatTs(iso: string): string {
  const d = Date.parse(iso)
  if (Number.isNaN(d)) return iso
  return new Date(d).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  })
}

function levelLabel(level: ProcessingLogEntry['level']): string {
  const m: Record<ProcessingLogEntry['level'], string> = {
    info: 'Инфо',
    warning: 'Внимание',
    error: 'Ошибка',
  }
  return m[level]
}
</script>

<template>
  <div class="plog">
    <ul class="plog__list" role="list">
      <li v-for="(ev, i) in entries" :key="i" class="plog__row">
        <time class="plog__time" :datetime="ev.ts">{{ formatTs(ev.ts) }}</time>
        <span
          class="plog__badge"
          :class="{
            'plog__badge--info': ev.level === 'info',
            'plog__badge--warn': ev.level === 'warning',
            'plog__badge--err': ev.level === 'error',
          }"
        >
          {{ levelLabel(ev.level) }}
        </span>
        <p class="plog__msg">{{ ev.message }}</p>
      </li>
    </ul>
    <button type="button" class="plog__raw-toggle" @click="showRaw = !showRaw">
      {{ showRaw ? 'Скрыть JSON' : 'Показать JSON (как в ответе API)' }}
    </button>
    <pre v-if="showRaw" class="plog__pre" tabindex="0">{{ jsonPretty }}</pre>
  </div>
</template>

<style scoped>
.plog__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.plog__row {
  display: grid;
  grid-template-columns: minmax(0, 11rem) auto 1fr;
  gap: 0.5rem 0.65rem;
  align-items: start;
  font-size: 0.86rem;
  line-height: 1.45;
}

@media (max-width: 640px) {
  .plog__row {
    grid-template-columns: 1fr;
  }
}

.plog__time {
  font-family: var(--font-mono);
  font-size: 0.78rem;
  color: var(--text-muted);
  white-space: nowrap;
}

.plog__badge {
  justify-self: start;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.12rem 0.4rem;
  border-radius: 4px;
  white-space: nowrap;
}

.plog__badge--info {
  background: color-mix(in srgb, var(--accent) 18%, var(--bg-muted));
  color: var(--accent);
}

.plog__badge--warn {
  background: color-mix(in srgb, #d97706 20%, var(--bg-muted));
  color: #b45309;
}

.plog__badge--err {
  background: var(--danger-soft);
  color: var(--danger);
}

.plog__msg {
  margin: 0;
  color: var(--text);
  grid-column: 1 / -1;
}

@media (min-width: 641px) {
  .plog__msg {
    grid-column: auto;
  }
}

.plog__raw-toggle {
  margin-top: 0.85rem;
  border: 1px solid var(--border);
  background: var(--bg-muted);
  color: var(--text-strong);
  padding: 0.4rem 0.75rem;
  border-radius: 8px;
  font-size: 0.85rem;
  cursor: pointer;
}

.plog__raw-toggle:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.plog__pre {
  margin: 0.65rem 0 0;
  padding: 0.85rem 1rem;
  border-radius: 8px;
  background: var(--bg-muted);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 0.76rem;
  line-height: 1.45;
  overflow-x: auto;
  color: var(--text);
}
</style>
