<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AudioPlayerPanel from '../components/audio/AudioPlayerPanel.vue'
import ProcessingLogPanel from '../components/report/ProcessingLogPanel.vue'
import RedactionReport from '../components/report/RedactionReport.vue'
import TranscriptPanel from '../components/transcript/TranscriptPanel.vue'
import PageIntro from '../components/ui/PageIntro.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import { isLoggedIn } from '../lib/auth'
import {
  connectProcessingStatusStream,
  fetchProcessingStatus,
  fetchUploadDetail,
  type ProcessingJobDetail,
  type ProcessingPollStatus,
} from '../lib/uploadsApi'
import { parseProcessingLogEntries } from '../lib/parseProcessingEvents'
import {
  durationFromWhisper,
  segmentsFromJob,
  statsFromReport,
  statusLabelRu,
  statusStageHintRu,
  timelineFromReport,
} from '../lib/resultMap'

const router = useRouter()
const r = useRoute()

const loading = ref(true)
const err = ref<string | null>(null)
const job = ref<ProcessingJobDetail | null>(null)
const fileName = ref('')
const storageUrl = ref('')
const completedViaPolling = ref(false)
/** Статус обработки из потока обновлений или периодической проверки. */
const pipelineStatus = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null
let wsStop: (() => void) | null = null

const uploadId = computed(() => String(r.params.uploadId ?? ''))

const displayStatus = computed(() => {
  const live = pipelineStatus.value
  if (live) return live
  return job.value?.status ?? ''
})

function shouldPoll(): boolean {
  const s = job.value?.status
  if (!s) return false
  return !['done', 'failed', 'cancelled'].includes(s)
}

const isProcessing = computed(() => {
  const s = displayStatus.value
  if (!s) return false
  return !['done', 'failed', 'cancelled'].includes(s)
})

const showWaitingBanner = computed(
  () => !loading.value && !err.value && !!job.value && isProcessing.value,
)

const hasStreamingPartialData = computed(() => {
  const j = job.value
  if (!j) return false
  if (j.transcript_plain || j.whisper_output) return true
  if (j.transcript_redacted || j.redaction_report || j.llm_entities) return true
  return false
})

const showSuccessBanner = computed(
  () =>
    !loading.value &&
    !err.value &&
    completedViaPolling.value &&
    job.value?.status === 'done',
)

const segments = computed(() =>
  segmentsFromJob(job.value?.whisper_output, job.value?.transcript_plain ?? ''),
)
const sanitizedText = computed(() => job.value?.transcript_redacted ?? '—')
const stats = computed(() => statsFromReport(job.value?.redaction_report))
const durationSec = computed(() => {
  const d = durationFromWhisper(job.value?.whisper_output)
  return d > 0 ? d : 120
})
const timeline = computed(() => timelineFromReport(job.value?.redaction_report, durationSec.value))

const processingLogEntries = computed(() => parseProcessingLogEntries(job.value?.processing_events))

async function load(silent = false) {
  if (!uploadId.value) return
  if (!silent) err.value = null
  try {
    const data = await fetchUploadDetail(uploadId.value)
    fileName.value = data.upload.original_filename
    storageUrl.value = data.upload.storage_url
    job.value = data.processing_job
    pipelineStatus.value = data.processing_job?.status ?? ''
    if (!silent) err.value = null
  } catch (e) {
    if (!silent) {
      err.value = e instanceof Error ? e.message : 'Ошибка загрузки'
      job.value = null
    }
  } finally {
    loading.value = false
  }
  if (shouldPoll()) {
    startWatch()
  } else {
    stopWatch()
  }
}

/** Подгрузка деталей job после смены этапа (данные в БД уже обновлены воркером). */
function maybeRefreshJobAfterStage(prev: string, next: string | undefined) {
  if (!next || next === prev) return
  if (next === 'llm' || next === 'render_audio') {
    void load(true)
  }
}

function applyPipelineStatusEvent(s: ProcessingPollStatus) {
  const prev = pipelineStatus.value
  if (s.status) pipelineStatus.value = s.status
  if (s.terminal) {
    completedViaPolling.value = true
    stopWatch()
    void load(true)
    return
  }
  maybeRefreshJobAfterStage(prev, s.status)
}

async function pollStatus() {
  if (!uploadId.value) return
  try {
    const s = await fetchProcessingStatus(uploadId.value)
    applyPipelineStatusEvent(s)
  } catch {
    if (!isLoggedIn()) {
      router.push({ name: 'login', query: { redirect: r.fullPath } })
      return
    }
  }
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPollFallback() {
  stopPoll()
  void pollStatus()
  pollTimer = setInterval(() => {
    void pollStatus()
  }, 2500)
}

function stopWatch() {
  if (wsStop) {
    wsStop()
    wsStop = null
  }
  stopPoll()
}

/** Подписка на статус: WebSocket, при сбое транспорта — периодический GET …/processing-status. */
function startWatch() {
  stopWatch()
  if (!uploadId.value || !shouldPoll()) return
  try {
    wsStop = connectProcessingStatusStream(
      uploadId.value,
      (s) => {
        applyPipelineStatusEvent(s)
      },
      () => {
        wsStop?.()
        wsStop = null
        startPollFallback()
      },
    )
  } catch {
    startPollFallback()
  }
}

onMounted(async () => {
  await load()
})

watch(uploadId, async () => {
  loading.value = true
  completedViaPolling.value = false
  pipelineStatus.value = ''
  await load()
})

onUnmounted(() => stopWatch())
</script>

<template>
  <div class="result">
    <PageIntro
      title="Результат обработки"
      subtitle="Транскрипт и отчёт появляются и обновляются по мере обработки записи."
    />

    <p v-if="loading" class="result__hint">Загрузка…</p>
    <p v-else-if="err" class="result__err">{{ err }}</p>

    <template v-else>
      <div
        v-if="showSuccessBanner"
        class="result__success"
        role="status"
        aria-live="polite"
      >
        <span class="result__success-icon" aria-hidden="true">✓</span>
        <div>
          <strong>Обработка завершена</strong>
          <p>Ниже — ваши транскрипт, отчёт и аудио.</p>
        </div>
      </div>

      <div v-if="!job" class="result__banner">
        <span class="result__badge">Нет данных</span>
        Обработка для этой записи ещё не началась или недоступна. Попробуйте загрузить файл снова.
      </div>

      <div
        v-else-if="job && !(showSuccessBanner && job.status === 'done')"
        class="result__strip"
        role="status"
        aria-live="polite"
      >
        <template v-if="showWaitingBanner">
          <span class="result__wait-spinner result__wait-spinner--inline" aria-hidden="true" />
          <div class="result__strip-main">
            <strong class="result__strip-title">{{ statusLabelRu(displayStatus) }}</strong>
            <span class="result__strip-hint">{{ statusStageHintRu(displayStatus) }}</span>
            <span v-if="hasStreamingPartialData" class="result__strip-partial">
              Разделы ниже будут дополняться по мере готовности.
            </span>
          </div>
        </template>
        <template v-else>
          <span
            class="result__badge"
            :class="{ 'result__badge--bad': displayStatus === 'failed' }"
          >
            {{ statusLabelRu(displayStatus) }}
          </span>
          <span v-if="job.error_message" class="result__err-msg">{{ job.error_message }}</span>
        </template>
      </div>

      <div v-if="job" class="result__grid">
        <UiCard title="Транскрипт" class="result__span2 result__card-priority">
          <TranscriptPanel :segments="segments" :sanitized-text="sanitizedText" />
        </UiCard>

        <UiCard title="Отчёт по удалённым данным" class="result__span2 result__card-priority">
          <p v-if="stats.length === 0" class="result__hint">
            Появится после поиска персональных данных в тексте: типы данных и примеры маскировки.
          </p>
          <RedactionReport v-else :rows="stats" />
        </UiCard>

        <UiCard title="Аудио" class="result__span2">
          <p v-if="storageUrl" class="result__link">
            <a :href="storageUrl" target="_blank" rel="noopener">Открыть исходный файл</a>
          </p>
          <AudioPlayerPanel
            :file-name="fileName || 'recording'"
            :duration-sec="durationSec"
            :redactions="timeline"
          />
        </UiCard>

        <UiCard v-if="processingLogEntries.length" title="Журнал обработки" class="result__span2">
          <ProcessingLogPanel :entries="processingLogEntries" />
        </UiCard>
      </div>
    </template>

    <div class="result__footer">
      <UiButton type="button" variant="secondary" to="/upload">Новая загрузка</UiButton>
      <UiButton type="button" variant="secondary" to="/demo">Пример экрана</UiButton>
      <UiButton type="button" variant="secondary" @click="router.push('/')">На главную</UiButton>
    </div>
  </div>
</template>

<style scoped>
.result :deep(.intro) {
  margin-bottom: 0.75rem;
}
.result__hint {
  margin: 0 0 1rem;
  color: var(--text-muted);
  font-size: 0.9rem;
}
.result__err {
  color: #c62828;
  margin: 0 0 1rem;
}
.result__strip {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  padding: 0.5rem 0.65rem;
  margin-bottom: 0.75rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-muted);
}
.result__strip-main {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
  flex: 1;
}
.result__strip-title {
  font-size: 0.88rem;
  font-weight: 650;
}
.result__strip-hint {
  font-size: 0.8rem;
  line-height: 1.4;
  color: var(--text-muted);
}
.result__strip-partial {
  font-size: 0.78rem;
  color: var(--accent);
  opacity: 0.95;
}
.result__wait-spinner {
  flex-shrink: 0;
  width: 1.1rem;
  height: 1.1rem;
  margin-top: 0.12rem;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: result-spin 0.85s linear infinite;
}
.result__wait-spinner--inline {
  margin-top: 0.2rem;
}
@keyframes result-spin {
  to {
    transform: rotate(360deg);
  }
}
.result__success {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.6rem 0.85rem;
  margin-bottom: 0.75rem;
  border-radius: var(--radius-sm);
  border: 1px solid color-mix(in srgb, #2e7d32 35%, var(--border));
  background: color-mix(in srgb, #2e7d32 12%, var(--bg-muted));
}
.result__success-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 50%;
  background: #2e7d32;
  color: #fff;
  font-size: 0.85rem;
  font-weight: 800;
  line-height: 1;
}
.result__success strong {
  display: block;
  font-size: 0.95rem;
  margin-bottom: 0.3rem;
  color: var(--text);
}
.result__success p {
  margin: 0;
  font-size: 0.86rem;
  line-height: 1.45;
  color: var(--text-muted);
}
.result__banner {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  padding: 0.75rem 1rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--accent-soft);
  font-size: 0.88rem;
  margin-bottom: 1rem;
}
.result__badge {
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 0.2rem 0.45rem;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
}
.result__badge--bad {
  background: #c62828;
}
.result__err-msg {
  font-size: 0.88rem;
  color: #c62828;
  flex: 1;
  min-width: 0;
}
.result__link {
  margin: 0 0 0.75rem;
  font-size: 0.88rem;
}
.result__link a {
  color: var(--accent);
}
.result__grid {
  display: grid;
  gap: 1rem;
}
.result__card-priority {
  scroll-margin-top: 0.5rem;
}
@media (min-width: 900px) {
  .result__grid {
    grid-template-columns: 1fr 1fr;
  }
  .result__span2 {
    grid-column: span 2;
  }
}
.result__footer {
  margin-top: 1.5rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}
</style>
