<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'

import PageIntro from '../components/ui/PageIntro.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import {
  convertAudioFileToMp3IfNeeded,
  createLiveMp3Capture,
  isLiveCaptureSupported,
  type LiveMp3Capture,
} from '../lib/recordToMp3'
import { uploadAudio } from '../lib/uploadsApi'

const router = useRouter()

const dragActive = ref(false)
const fileName = ref<string | null>(null)
const fileRef = ref<File | null>(null)
const note = ref('')
const loading = ref(false)

const recording = ref(false)
const encoding = ref(false)
const converting = ref(false)
let liveCapture: LiveMp3Capture | null = null

const canUseMic = computed(() => isLiveCaptureSupported())

function onDrop(e: DragEvent) {
  e.preventDefault()
  dragActive.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) void processPickedFile(f)
}

function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (f) void processPickedFile(f)
  input.value = ''
}

function looksLikeAudioFile(f: File): boolean {
  if (f.type.startsWith('audio/')) {
    return true
  }
  const n = f.name.toLowerCase()
  return ['.mp3', '.wav', '.ogg', '.oga', '.opus', '.webm', '.m4a', '.aac', '.flac', '.mp4', '.caf'].some(
    (ext) => n.endsWith(ext),
  )
}

async function processPickedFile(f: File) {
  if (recording.value) {
    requestCancelRecording()
  }
  if (!looksLikeAudioFile(f)) {
    fileName.value = null
    fileRef.value = null
    note.value =
      'Нужен аудиофайл (например WAV, OGG, M4A, FLAC). Расширение или тип MIME должны быть аудио.'
    return
  }
  fileRef.value = null
  fileName.value = null
  const isAlreadyMp3 = f.name.trim().toLowerCase().endsWith('.mp3')
  try {
    if (!isAlreadyMp3) {
      converting.value = true
      note.value = 'Конвертация в MP3 в браузере…'
    } else {
      note.value = ''
    }
    const ready = await convertAudioFileToMp3IfNeeded(f)
    fileRef.value = ready
    fileName.value = ready.name
    note.value = isAlreadyMp3 ? '' : 'Файл сконвертирован в MP3. Нажмите «Загрузить и обработать».'
  } catch (e) {
    fileName.value = null
    fileRef.value = null
    if (e instanceof Error) {
      if (e.message === 'file_too_large') {
        note.value = 'Файл больше 50 МБ — такой же лимит на сервере.'
      } else if (e.message === 'decode_failed') {
        note.value =
          'Браузер не смог прочитать этот контейнер/кодек. Сохраните как WAV или MP3 и попробуйте снова.'
      } else if (e.message === 'too_short') {
        note.value = 'В файле слишком мало аудио.'
      } else {
        note.value = `Не удалось сделать MP3: ${e.message}`
      }
    } else {
      note.value = 'Не удалось сделать MP3.'
    }
  } finally {
    converting.value = false
  }
}

function requestCancelRecording() {
  console.log('[upload-view] requestCancelRecording')
  liveCapture?.cancel()
  liveCapture = null
  recording.value = false
}

async function startRecording() {
  console.log('[upload-view] startRecording click, canUseMic=', canUseMic.value)
  if (!canUseMic.value) {
    note.value = 'В этом браузере недоступна запись с микрофона.'
    console.warn('[upload-view] blocked: isLiveCaptureSupported() is false — см. логи [record-mp3]')
    return
  }
  note.value = ''
  liveCapture?.cancel()
  liveCapture = null
  fileRef.value = null
  fileName.value = null
  try {
    liveCapture = createLiveMp3Capture()
    await liveCapture.start()
    recording.value = true
    console.log('[upload-view] startRecording OK, recording=true')
  } catch (e) {
    console.error('[upload-view] startRecording FAILED', e)
    if (e instanceof Error) {
      console.error('[upload-view] stack', e.stack)
    }
    note.value = 'Не удалось получить доступ к микрофону. Разрешите запись в настройках браузера. Подробности в консоли (F12).'
    liveCapture = null
    recording.value = false
  }
}

async function stopRecording() {
  console.log('[upload-view] stopRecording click')
  const cap = liveCapture
  if (!cap) {
    console.warn('[upload-view] stopRecording: no active liveCapture')
    return
  }
  liveCapture = null
  recording.value = false
  encoding.value = true
  note.value = ''
  try {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5)
    const name = `nadiktovka-${stamp}.mp3`
    const file = await cap.stop(name)
    fileRef.value = file
    fileName.value = file.name
    note.value = 'Запись сохранена как MP3. Нажмите «Загрузить и обработать».'
    console.log('[upload-view] stopRecording OK, file.size=', file.size, file.name)
  } catch (e) {
    console.error('[upload-view] stopRecording FAILED', e)
    if (e instanceof Error) {
      console.error('[upload-view] stack', e.stack)
    }
    const short = e instanceof Error && e.message === 'too_short'
    note.value = short
      ? 'Запись слишком короткая — задержите кнопку чуть дольше.'
      : 'Не удалось сохранить MP3. Подробности в консоли (F12).'
  } finally {
    encoding.value = false
  }
}

onBeforeUnmount(() => {
  liveCapture?.cancel()
  liveCapture = null
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

const uploadDisabled = computed(
  () => loading.value || encoding.value || converting.value || !fileRef.value,
)
const recordBusy = computed(() => recording.value || encoding.value || converting.value)
</script>

<template>
  <div class="upload">
    <PageIntro
      title="Загрузка записи"
      subtitle="Войдите в аккаунт. Подойдёт MP3 или другой аудиоформат: в браузере он будет переведён в MP3 перед отправкой. Можно также надиктовать в микрофон."
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
            accept="audio/*,.mp3,.wav,.ogg,.oga,.opus,.webm,.m4a,.aac,.flac,.mp4,.caf"
            :disabled="recordBusy"
            @change="onFile"
          />
          <span class="drop__icon" aria-hidden="true">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M12 5v11m0 0l-3.5-3.5M12 16l3.5-3.5M5 19h14" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
          <span class="drop__title">Перетащите аудио сюда</span>
          <span class="drop__sub">WAV, OGG, M4A… — перед загрузкой станет MP3 в этом окне</span>
        </label>
      </div>

      <p v-if="fileName" class="upload__picked">
        Выбрано: <strong>{{ fileName }}</strong>
      </p>
      <p v-if="note" class="upload__note">{{ note }}</p>

      <div class="upload__row">
        <UiButton type="button" variant="primary" :disabled="uploadDisabled" @click="upload">
          {{
            loading ? 'Загрузка…' : converting ? 'Конвертация…' : 'Загрузить и обработать'
          }}
        </UiButton>
      </div>
    </UiCard>

    <UiCard v-if="canUseMic" class="upload__mic-card" title="Надиктовка">
      <p class="upload__mic-hint">
        Аудио с микрофона кодируется в MP3 на устройстве.
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
