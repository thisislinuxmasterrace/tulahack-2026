<script setup lang="ts">
import { computed } from 'vue'

import { uploadOriginalStreamUrl, uploadRedactedStreamUrl } from '../../lib/mediaUrls'

const props = defineProps<{
  uploadId: string
  originalFilename: string
  redactedAvailable: boolean
}>()

function safeBaseName(name: string): string {
  const t = name.trim() || 'audio'
  return t.replace(/[\\/:*?"<>|]+/g, '_')
}

const originalHref = computed(() => uploadOriginalStreamUrl(props.uploadId, { download: true }))
const redactedHref = computed(() =>
  props.redactedAvailable ? uploadRedactedStreamUrl(props.uploadId, { download: true }) : '',
)
</script>

<template>
  <div class="dl">
    <a
      class="dl__btn"
      :href="originalHref"
      :title="`Скачать ${safeBaseName(originalFilename)}`"
    >
      <span class="dl__icon" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 3v12m0 0l4-4m-4 4L8 11M4 21h16" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </span>
      Исходное аудио
    </a>
    <a
      v-if="redactedAvailable && redactedHref"
      class="dl__btn dl__btn--accent"
      :href="redactedHref"
      :title="`Скачать redacted_${safeBaseName(originalFilename)}`"
    >
      <span class="dl__icon" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 3v12m0 0l4-4m-4 4L8 11M4 21h16" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </span>
      Обработанное аудио
    </a>
  </div>
</template>

<style scoped>
.dl {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.dl__btn {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.45rem 0.9rem;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 600;
  text-decoration: none;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-strong);
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s;
}

.dl__btn:hover {
  background: var(--bg-muted);
  border-color: var(--border-strong);
  text-decoration: none;
}

.dl__btn--accent {
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  background: var(--accent-soft);
  color: var(--accent);
}

.dl__btn--accent:hover {
  background: color-mix(in srgb, var(--accent) 18%, var(--bg-elevated));
  border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
}

.dl__icon {
  display: flex;
  opacity: 0.85;
}
</style>
