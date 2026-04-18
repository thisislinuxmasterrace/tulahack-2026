<script setup lang="ts">
import { ref } from 'vue'

import type { TranscriptSegment } from '../../types/result'

defineProps<{
  segments: TranscriptSegment[]
  sanitizedText: string
}>()

const tab = ref<'original' | 'sanitized'>('original')
</script>

<template>
  <div class="tx">
    <div class="tx__tabs" role="tablist" aria-label="Вариант транскрипта">
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'original'"
        class="tx__tab"
        :class="{ 'tx__tab--on': tab === 'original' }"
        @click="tab = 'original'"
      >
        С персональными данными
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'sanitized'"
        class="tx__tab"
        :class="{ 'tx__tab--on': tab === 'sanitized' }"
        @click="tab = 'sanitized'"
      >
        Обезличенный
      </button>
    </div>

    <div
      class="tx__body"
      role="tabpanel"
      :aria-label="tab === 'original' ? 'Исходный текст' : 'Текст без персональных данных'"
    >
      <template v-if="tab === 'original'">
        <p class="tx__text">
          <template v-for="(seg, i) in segments" :key="i">
            <mark v-if="seg.sensitive" class="tx__mark" :title="seg.category ?? 'персональные данные'">
              {{ seg.text }}
            </mark>
            <span v-else>{{ seg.text }}</span>
          </template>
        </p>
      </template>
      <template v-else>
        <p class="tx__text tx__text--plain">{{ sanitizedText }}</p>
        <p class="tx__hint">Текст после маскировки персональных данных.</p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.tx__tabs {
  display: flex;
  gap: 0.35rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

.tx__tab {
  border: 1px solid var(--border);
  background: var(--bg-muted);
  color: var(--text-muted);
  padding: 0.4rem 0.85rem;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s,
    border-color 0.15s;
}

.tx__tab:hover {
  color: var(--text-strong);
}

.tx__tab--on {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft);
}

.tx__body {
  min-height: 8rem;
}

.tx__text {
  margin: 0;
  font-size: 0.95rem;
  line-height: 1.65;
  color: var(--text);
}

.tx__text--plain {
  font-family: var(--font-mono);
  font-size: 0.88rem;
  color: var(--text-muted);
}

.tx__mark {
  background: var(--danger-soft);
  color: var(--text-strong);
  border-radius: 4px;
  padding: 0.05em 0.15em;
}

.tx__hint {
  margin: 0.85rem 0 0;
  font-size: 0.78rem;
  color: var(--text-muted);
}
</style>
