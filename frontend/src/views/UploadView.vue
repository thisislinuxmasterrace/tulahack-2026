<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import PageIntro from '../components/ui/PageIntro.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import { uploadAudio } from '../lib/uploadsApi'

const router = useRouter()

const dragActive = ref(false)
const fileName = ref<string | null>(null)
const fileRef = ref<File | null>(null)
const note = ref('')
const loading = ref(false)
const resultUrl = ref<string | null>(null)
const queueInfo = ref<string | null>(null)

function onDrop(e: DragEvent) {
  e.preventDefault()
  dragActive.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) pickFile(f)
}

function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (f) pickFile(f)
}

function pickFile(f: File) {
  fileName.value = f.name
  fileRef.value = f
  resultUrl.value = null
  queueInfo.value = null
  note.value = ''
}

async function upload() {
  const f = fileRef.value
  if (!f) {
    note.value = 'Сначала выберите файл.'
    return
  }
  note.value = ''
  loading.value = true
  resultUrl.value = null
  queueInfo.value = null
  try {
    const data = await uploadAudio(f)
    resultUrl.value = data.upload.storage_url
    const uploadId = data.upload.id
    if (uploadId) {
      router.push({ name: 'result', params: { uploadId } })
    }
    const q = data.queue
    if (q.enqueued) {
      queueInfo.value = 'Файл принят, обработка поставлена в очередь.'
      note.value = 'Скоро откроется страница с ходом обработки.'
    } else if (q.reason === 'redis_disabled') {
      queueInfo.value = 'Файл сохранён.'
      note.value = 'Очередь обработки на стороне сервиса сейчас не используется — обратитесь к администратору, если обработка не начинается.'
    } else if (q.error) {
      queueInfo.value = 'Не удалось поставить задачу в очередь.'
      note.value = `Файл сохранён. ${q.error}. Если проблема повторяется, обратитесь к администратору.`
    } else {
      note.value = 'Файл сохранён.'
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Ошибка загрузки'
    note.value = msg
    if (msg.includes('войдите') || msg.toLowerCase().includes('session')) {
      router.push({ name: 'login', query: { redirect: '/upload' } })
    }
  } finally {
    loading.value = false
  }
}

</script>

<template>
  <div class="upload">
    <PageIntro
      title="Загрузка записи"
      subtitle="Войдите в аккаунт, затем перетащите аудиофайл сюда или выберите его на устройстве. Подойдут распространённые форматы записи."
    />

    <UiCard title="Файл">
      <div
        class="drop"
        :class="{ 'drop--on': dragActive }"
        @dragenter.prevent="dragActive = true"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop="onDrop"
      >
        <label class="drop__label">
          <input
            class="drop__input"
            type="file"
            accept="audio/*,.wav,.mp3,.ogg,.webm"
            @change="onFile"
          />
          <span class="drop__icon" aria-hidden="true">⬆</span>
          <span class="drop__title">Перетащите аудио сюда</span>
          <span class="drop__sub">или нажмите, чтобы выбрать файл</span>
        </label>
      </div>

      <p v-if="fileName" class="upload__picked">
        Выбрано: <strong>{{ fileName }}</strong>
      </p>
      <p v-if="note" class="upload__note">{{ note }}</p>

      <div v-if="resultUrl" class="upload__result">
        <p class="upload__result-title">Ссылка на сохранённый файл</p>
        <code class="upload__code">{{ resultUrl }}</code>
        <p v-if="queueInfo" class="upload__queue">{{ queueInfo }}</p>
        <p class="upload__hint">Если ссылка не открывается в браузере, попробуйте позже или обратитесь в поддержку.</p>
      </div>

      <div class="upload__row">
        <UiButton type="button" variant="primary" :disabled="loading || !fileRef" @click="upload">
          {{ loading ? 'Загрузка…' : 'Загрузить и обработать' }}
        </UiButton>
        <UiButton type="button" variant="secondary" to="/demo">Пример экрана</UiButton>
      </div>
    </UiCard>
  </div>
</template>

<style scoped>
.drop {
  position: relative;
  border: 2px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--bg-muted);
  transition:
    border-color 0.15s,
    background 0.15s;
}

.drop--on {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.drop__label {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 2.25rem 1rem;
  cursor: pointer;
  text-align: center;
}

.drop__input {
  position: absolute;
  inset: 0;
  opacity: 0;
  width: 100%;
  height: 100%;
  cursor: pointer;
}

.drop__icon {
  font-size: 1.5rem;
  opacity: 0.75;
}

.drop__title {
  font-weight: 600;
  color: var(--text-strong);
}

.drop__sub {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.upload__picked {
  margin: 1rem 0 0;
  font-size: 0.9rem;
  color: var(--text-muted);
}

.upload__picked strong {
  color: var(--text-strong);
}

.upload__note {
  margin: 0.6rem 0 0;
  font-size: 0.82rem;
  color: var(--text-muted);
  line-height: 1.45;
}

.upload__result {
  margin-top: 1rem;
  padding: 0.85rem 1rem;
  border-radius: var(--radius-sm);
  background: var(--bg-muted);
  border: 1px solid var(--border);
}

.upload__result-title {
  margin: 0 0 0.35rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.upload__code {
  display: block;
  font-size: 0.78rem;
  word-break: break-all;
  margin-bottom: 0.75rem;
  color: var(--text-strong);
}

.upload__queue {
  margin: 0.65rem 0 0;
  font-size: 0.85rem;
  color: var(--accent);
  font-weight: 600;
}

.upload__hint {
  margin: 0.5rem 0 0;
  font-size: 0.78rem;
  color: var(--text-muted);
  line-height: 1.4;
}

.upload__row {
  margin-top: 1.25rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}
</style>
