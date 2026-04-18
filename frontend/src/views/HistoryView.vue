<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import PageIntro from '../components/ui/PageIntro.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import { onAccessTokenChanged } from '../lib/auth'
import { uploadOriginalStreamUrl, uploadRedactedStreamUrl } from '../lib/mediaUrls'
import { fetchUploadsList, type UploadListRow } from '../lib/uploadsApi'
import { statusLabelRu } from '../lib/resultMap'

const router = useRouter()

const loading = ref(true)
const err = ref<string | null>(null)
const rows = ref<UploadListRow[]>([])
/** Зависимость для ссылок с access_token — обновление после refresh. */
const mediaUrlEpoch = ref(0)
let unsubMediaTokens: (() => void) | null = null

function formatWhen(iso: string) {
  try {
    return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
  } catch {
    return iso
  }
}

function statusRu(row: UploadListRow) {
  const s = row.processing_job?.status ?? ''
  return s ? statusLabelRu(s) : '—'
}

function openRow(uploadId: string) {
  router.push({ name: 'result', params: { uploadId } })
}

function downloadOriginalHref(id: string) {
  void mediaUrlEpoch.value
  return uploadOriginalStreamUrl(id, { download: true })
}

function downloadRedactedHref(id: string) {
  void mediaUrlEpoch.value
  return uploadRedactedStreamUrl(id, { download: true })
}

function safeDownloadName(name: string): string {
  const t = name.trim() || 'audio'
  return t.replace(/[\\/:*?"<>|]+/g, '_')
}

onMounted(async () => {
  unsubMediaTokens = onAccessTokenChanged(() => {
    mediaUrlEpoch.value += 1
  })
  loading.value = true
  err.value = null
  try {
    const data = await fetchUploadsList(100)
    rows.value = data.uploads ?? []
  } catch (e) {
    err.value = e instanceof Error ? e.message : 'Не удалось загрузить список'
    rows.value = []
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  unsubMediaTokens?.()
  unsubMediaTokens = null
})
</script>

<template>
  <div class="history">
    <PageIntro
      title="История обработок"
      subtitle="Выберите запись, чтобы открыть тот же экран результата: транскрипт, отчёт и аудио."
    />

    <UiCard title="Ваши загрузки">
      <p v-if="loading" class="history__hint">Загрузка…</p>
      <p v-else-if="err" class="history__err">{{ err }}</p>
      <p v-else-if="rows.length === 0" class="history__hint">
        Пока нет загрузок. После обработки записей они появятся здесь.
      </p>
      <ul v-else class="history__list" aria-label="Список обработок">
        <li v-for="item in rows" :key="item.upload.id">
          <div class="history__row">
            <button type="button" class="history__hit" @click="openRow(item.upload.id)">
              <span class="history__name">{{ item.upload.original_filename }}</span>
              <span class="history__meta">{{ formatWhen(item.upload.created_at) }}</span>
              <span class="history__status" :data-terminal="item.processing_job?.status === 'done'">
                {{ statusRu(item) }}
              </span>
            </button>
            <div class="history__dl" @click.stop>
              <a
                class="history__dl-btn"
                :href="downloadOriginalHref(item.upload.id)"
                :download="safeDownloadName(item.upload.original_filename)"
                :title="`Скачать исходное: ${item.upload.original_filename}`"
                aria-label="Скачать исходное аудио"
              >
                <span class="history__dl-ic" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 3v12m0 0l4-4m-4 4L8 11M4 21h16" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </span>
                <span class="sr-only">Исходное</span>
              </a>
              <a
                v-if="item.processing_job?.status === 'done'"
                class="history__dl-btn history__dl-btn--accent"
                :href="downloadRedactedHref(item.upload.id)"
                :download="`redacted_${safeDownloadName(item.upload.original_filename)}`"
                title="Скачать обработанное аудио"
                aria-label="Скачать обработанное аудио"
              >
                <span class="history__dl-ic" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 3v12m0 0l4-4m-4 4L8 11M4 21h16" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </span>
                <span class="sr-only">Обработанное</span>
              </a>
            </div>
          </div>
        </li>
      </ul>
    </UiCard>

    <div class="history__footer">
      <UiButton type="button" variant="secondary" to="/upload">Новая загрузка</UiButton>
    </div>
  </div>
</template>

<style scoped>
.history__hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.9rem;
}
.history__err {
  margin: 0;
  color: #c62828;
  font-size: 0.9rem;
}
.history__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.history__row {
  width: 100%;
  display: flex;
  align-items: stretch;
  gap: 0.5rem;
  padding: 0.85rem 1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
  transition:
    border-color 0.15s,
    background 0.15s;
}
.history__row:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.history__hit {
  flex: 1;
  min-width: 0;
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 0.75rem 1rem;
  align-items: center;
  text-align: left;
  padding: 0;
  border: none;
  border-radius: 0;
  background: transparent;
  cursor: pointer;
  font: inherit;
  color: inherit;
}
.history__hit:focus-visible {
  outline: 2px solid var(--accent-ring);
  outline-offset: 2px;
  border-radius: 6px;
}
.history__dl {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.history__dl-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg-muted);
  color: var(--text-strong);
  text-decoration: none;
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s;
}
.history__dl-btn:hover {
  background: var(--bg-elevated);
  border-color: var(--border-strong);
}
.history__dl-btn--accent {
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  background: var(--accent-soft);
  color: var(--accent);
}
.history__dl-btn--accent:hover {
  background: color-mix(in srgb, var(--accent) 18%, var(--bg-elevated));
  border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
}
.history__dl-ic {
  display: flex;
  opacity: 0.9;
}
.history__name {
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history__meta {
  font-size: 0.82rem;
  color: var(--text-muted);
  white-space: nowrap;
}
.history__status {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-muted);
  white-space: nowrap;
}
.history__status[data-terminal='true'] {
  color: var(--accent);
}
.history__footer {
  margin-top: 1.25rem;
}
@media (max-width: 640px) {
  .history__hit {
    grid-template-columns: 1fr;
    gap: 0.35rem;
  }
  .history__meta,
  .history__status {
    justify-self: start;
  }
  .history__row {
    flex-wrap: wrap;
  }
  .history__dl {
    width: 100%;
    justify-content: flex-end;
    padding-top: 0.25rem;
  }
}
</style>
