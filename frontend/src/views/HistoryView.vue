<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import PageIntro from '../components/ui/PageIntro.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import { fetchUploadsList, type UploadListRow } from '../lib/uploadsApi'
import { statusLabelRu } from '../lib/resultMap'

const router = useRouter()

const loading = ref(true)
const err = ref<string | null>(null)
const rows = ref<UploadListRow[]>([])

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

onMounted(async () => {
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
          <button type="button" class="history__row" @click="openRow(item.upload.id)">
            <span class="history__name">{{ item.upload.original_filename }}</span>
            <span class="history__meta">{{ formatWhen(item.upload.created_at) }}</span>
            <span class="history__status" :data-terminal="item.processing_job?.status === 'done'">
              {{ statusRu(item) }}
            </span>
          </button>
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
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 0.75rem 1rem;
  align-items: center;
  text-align: left;
  padding: 0.85rem 1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
  cursor: pointer;
  font: inherit;
  color: inherit;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.history__row:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.history__row:focus-visible {
  outline: 2px solid var(--accent-ring);
  outline-offset: 2px;
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
  .history__row {
    grid-template-columns: 1fr;
    gap: 0.35rem;
  }
  .history__meta,
  .history__status {
    justify-self: start;
  }
}
</style>
