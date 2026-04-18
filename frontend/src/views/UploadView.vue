<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'

import PageIntro from '../components/ui/PageIntro.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import { preferredRecorderMimeType, recordedBlobToMp3File } from '../lib/recordToMp3'
import { uploadAudio } from '../lib/uploadsApi'

const router = useRouter()

const dragActive = ref(false)
const fileName = ref<string | null>(null)
const fileRef = ref<File | null>(null)
const note = ref('')
const loading = ref(false)

const recording = ref(false)
const encoding = ref(false)
const cancelRequested = ref(false)
const micStream = ref<MediaStream | null>(null)
const mediaRecorder = ref<MediaRecorder | null>(null)
let recordChunksBuf: Blob[] = []

const canUseMic = computed(
  () =>
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined',
)

function stopMicTracks() {
  micStream.value?.getTracks().forEach((t) => t.stop())
  micStream.value = null
}

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

function isMp3File(f: File): boolean {
  const n = f.name.trim().toLowerCase()
  return n.endsWith('.mp3')
}

function requestCancelRecording() {
  cancelRequested.value = true
  const mr = mediaRecorder.value
  if (mr && mr.state !== 'inactive') {
    mr.stop()
  } else {
    cancelRequested.value = false
    recordChunksBuf = []
    recording.value = false
    stopMicTracks()
    mediaRecorder.value = null
  }
}

function pickFile(f: File) {
  if (recording.value) {
    requestCancelRecording()
  }
  if (!isMp3File(f)) {
    fileName.value = null
    fileRef.value = null
    note.value = 'Поддерживается только формат MP3. Выберите файл с расширением .mp3.'
    return
  }
  fileName.value = f.name
  fileRef.value = f
  note.value = ''
}

async function startRecording() {
  if (!canUseMic.value) {
    note.value = 'В этом браузере недоступна запись с микрофона.'
    return
  }
  note.value = ''
  cancelRequested.value = false
  recordChunksBuf = []
  fileRef.value = null
  fileName.value = null
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
      },
    })
    micStream.value = stream
    const mime = preferredRecorderMimeType()
    const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
    mediaRecorder.value = mr
    mr.ondataavailable = (ev) => {
      if (ev.data.size > 0) {
        recordChunksBuf.push(ev.data)
      }
    }
    mr.onstop = () => {
      stopMicTracks()
      mediaRecorder.value = null
      const dropped = cancelRequested.value
      cancelRequested.value = false
      const chunks = recordChunksBuf
      recordChunksBuf = []
      recording.value = false
      if (dropped) {
        return
      }
      const mimeType = mr.mimeType || 'audio/webm'
      const recorded = new Blob(chunks, { type: mimeType })
      void finishRecordingToMp3(recorded)
    }
    mr.start(250)
    recording.value = true
  } catch {
    note.value = 'Не удалось получить доступ к микрофону. Разрешите запись в настройках браузера.'
    recording.value = false
    stopMicTracks()
    mediaRecorder.value = null
    recordChunksBuf = []
  }
}

async function finishRecordingToMp3(recorded: Blob) {
  encoding.value = true
  try {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5)
    const name = `nadiktovka-${stamp}.mp3`
    const file = await recordedBlobToMp3File(recorded, name)
    fileRef.value = file
    fileName.value = file.name
    note.value = 'Запись сохранена как MP3. Нажмите «Загрузить и обработать».'
  } catch {
    note.value =
      'Не удалось преобразовать запись в MP3. Попробуйте другой браузер или загрузите готовый .mp3 файл.'
  } finally {
    encoding.value = false
  }
}

function stopRecording() {
  cancelRequested.value = false
  const mr = mediaRecorder.value
  if (mr && mr.state !== 'inactive') {
    mr.stop()
  }
}

onBeforeUnmount(() => {
  cancelRequested.value = true
  const mr = mediaRecorder.value
  if (mr && mr.state !== 'inactive') {
    mr.stop()
  } else {
    stopMicTracks()
    mediaRecorder.value = null
    recordChunksBuf = []
    recording.value = false
  }
})

async function upload() {
  const f = fileRef.value
  if (!f) {
    note.value = 'Сначала выберите файл или запишите аудио.'
    return
  }
  note.value = ''
  loading.value = true
  try {
    const data = await uploadAudio(f)
    const uploadId = data.upload.id
    if (uploadId) {
      router.push({ name: 'result', params: { uploadId } })
    }
    const q = data.queue
    if (q.enqueued) {
      note.value = 'Файл принят, открываем страницу обработки…'
    } else if (q.reason === 'redis_disabled') {
      note.value =
        'Файл сохранён. Очередь обработки сейчас отключена — обратитесь к администратору, если задача не появится.'
    } else if (q.error) {
      note.value = `Файл сохранён, но очередь недоступна: ${q.error}`
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

const uploadDisabled = computed(() => loading.value || encoding.value || !fileRef.value)
const recordBusy = computed(() => recording.value || encoding.value)
</script>

<template>
  <div class="upload">
    <PageIntro
      title="Загрузка записи"
      subtitle="Войдите в аккаунт. Можно загрузить готовый MP3, надиктовать текст в микрофон (сохранится как MP3) или перетащить файл сюда."
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
            accept=".mp3,audio/mpeg,audio/mp3"
            :disabled="recording || encoding"
            @change="onFile"
          />
          <span class="drop__icon" aria-hidden="true">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M12 5v11m0 0l-3.5-3.5M12 16l3.5-3.5M5 19h14" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
          <span class="drop__title">Перетащите MP3 сюда</span>
          <span class="drop__sub">или нажмите, чтобы выбрать .mp3</span>
        </label>
      </div>

      <p v-if="fileName" class="upload__picked">
        Выбрано: <strong>{{ fileName }}</strong>
      </p>
      <p v-if="note" class="upload__note">{{ note }}</p>

      <div class="upload__row">
        <UiButton type="button" variant="primary" :disabled="uploadDisabled" @click="upload">
          {{ loading ? 'Загрузка…' : 'Загрузить и обработать' }}
        </UiButton>
      </div>
    </UiCard>

    <UiCard v-if="canUseMic" class="upload__mic-card" title="Надиктовка">
      <p class="upload__mic-hint">
        Запись в браузере конвертируется в MP3 на устройстве и отправляется так же, как при выборе файла.
      </p>
      <div class="upload__row upload__row--mic">
        <UiButton
          type="button"
          variant="primary"
          :disabled="recordBusy || loading"
          @click="startRecording"
        >
          {{ recording ? 'Идёт запись…' : encoding ? 'Обработка…' : 'Начать запись' }}
        </UiButton>
        <UiButton
          type="button"
          variant="secondary"
          :disabled="!recording || loading"
          @click="stopRecording"
        >
          Закончить и сохранить
        </UiButton>
        <UiButton type="button" variant="ghost" :disabled="!recording || loading" @click="requestCancelRecording">
          Отменить
        </UiButton>
      </div>
    </UiCard>
    <p v-else class="upload__no-mic">Запись с микрофона в этом браузере недоступна — используйте загрузку файла.</p>
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

.drop__input:disabled + .drop__icon,
.drop__input:disabled ~ .drop__title,
.drop__input:disabled ~ .drop__sub {
  opacity: 0.45;
}

.drop__input:disabled {
  cursor: not-allowed;
  pointer-events: none;
}

.drop__icon {
  display: flex;
  color: var(--accent);
  opacity: 0.85;
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

.upload__row {
  margin-top: 1.25rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}

.upload__mic-card {
  margin-top: 1rem;
}

.upload__mic-hint {
  margin: 0;
  font-size: 0.85rem;
  color: var(--text-muted);
  line-height: 1.45;
}

.upload__row--mic {
  margin-top: 1rem;
}

.upload__no-mic {
  margin: 1rem 0 0;
  font-size: 0.85rem;
  color: var(--text-muted);
}
</style>
