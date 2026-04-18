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
import { ensureAccessTokenFresh, getAccessToken, isLoggedIn, onAccessTokenChanged } from '../lib/auth'
import { uploadOriginalStreamUrl, uploadRedactedStreamUrl } from '../lib/mediaUrls'
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
/** true после завершения по стриму/опросу или при открытии уже готовой записи (история). */
const completedViaPolling = ref(false)
const pipelineStatus = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null
let wsStop: (() => void) | null = null
let jobRefreshDebounce: ReturnType<typeof setTimeout> | null = null

function scheduleJobDetailRefresh() {
  if (jobRefreshDebounce) clearTimeout(jobRefreshDebounce)
  jobRefreshDebounce = setTimeout(() => {
    jobRefreshDebounce = null
    void load(true)
  }, 320)
}

const uploadId = computed(() => String(r.params.uploadId ?? ''))

/** Пересборка URL с `?access_token=` после refresh в localStorage. */
const mediaUrlEpoch = ref(0)
let mediaRefreshTimer: ReturnType<typeof setInterval> | null = null
let unsubMediaTokens: (() => void) | null = null

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
  segmentsFromJob(
    job.value?.whisper_output,
    job.value?.transcript_plain ?? '',
    job.value?.llm_entities,
  ),
)
const sanitizedText = computed(() => job.value?.transcript_redacted ?? '—')
const stats = computed(() => statsFromReport(job.value?.redaction_report))
const durationSec = computed(() => {
  const d = durationFromWhisper(job.value?.whisper_output)
  return d > 0 ? d : 120
})
const timeline = computed(() => timelineFromReport(job.value?.redaction_report, durationSec.value))

const processingLogEntries = computed(() => parseProcessingLogEntries(job.value?.processing_events))

const redactedAudioUrl = computed(() => (job.value?.redacted_audio_storage_url || '').trim())

const listenTrack = ref<'original' | 'redacted'>('original')

watch(
  () => [job.value?.status, redactedAudioUrl.value] as const,
  () => {
    if (job.value?.status === 'done' && redactedAudioUrl.value) {
      listenTrack.value = 'redacted'
    } else {
      listenTrack.value = 'original'
    }
  },
  { immediate: true },
)

const showTrackSwitch = computed(
  () => job.value?.status === 'done' && !!redactedAudioUrl.value && !!uploadId.value,
)

const playbackUrl = computed(() => {
  void mediaUrlEpoch.value
  if (!uploadId.value || !getAccessToken()) return null
  if (listenTrack.value === 'redacted' && job.value?.status === 'done' && redactedAudioUrl.value) {
    return uploadRedactedStreamUrl(uploadId.value)
  }
  return uploadOriginalStreamUrl(uploadId.value)
})

const originalDownloadHref = computed(() => {
  void mediaUrlEpoch.value
  if (!uploadId.value || !getAccessToken()) return null
  return uploadOriginalStreamUrl(uploadId.value, { download: true })
})

const redactedDownloadHref = computed(() => {
  void mediaUrlEpoch.value
  if (!uploadId.value || !getAccessToken()) return null
  if (job.value?.status !== 'done' || !redactedAudioUrl.value) return null
  return uploadRedactedStreamUrl(uploadId.value, { download: true })
})

async function load(silent = false) {
  if (!uploadId.value) return
  if (!silent) err.value = null
  try {
    const data = await fetchUploadDetail(uploadId.value)
    fileName.value = data.upload.original_filename
    job.value = data.processing_job
    pipelineStatus.value = data.processing_job?.status ?? ''
    if (data.processing_job?.status === 'done') {
      completedViaPolling.value = true
    }
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
    if (!wsStop && !pollTimer) {
      void startWatch()
    }
  } else {
    stopWatch()
  }
}

function applyPipelineStatusEvent(s: ProcessingPollStatus) {
  if (s.status) pipelineStatus.value = s.status
  if (s.terminal) {
    completedViaPolling.value = true
    stopWatch()
    if (jobRefreshDebounce) {
      clearTimeout(jobRefreshDebounce)
      jobRefreshDebounce = null
    }
    void load(true)
    return
  }
  scheduleJobDetailRefresh()
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

async function startWatch() {
  stopWatch()
  if (!uploadId.value || !shouldPoll()) return
  try {
    wsStop = await connectProcessingStatusStream(
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
  unsubMediaTokens = onAccessTokenChanged(() => {
    mediaUrlEpoch.value += 1
  })
  mediaRefreshTimer = setInterval(() => {
    void ensureAccessTokenFresh()
  }, 60_000)
  await load()
})

watch(uploadId, async () => {
  stopWatch()
  loading.value = true
  completedViaPolling.value = false
  pipelineStatus.value = ''
  await load()
})

onUnmounted(() => {
  stopWatch()
  unsubMediaTokens?.()
  unsubMediaTokens = null
  if (mediaRefreshTimer) {
    clearInterval(mediaRefreshTimer)
    mediaRefreshTimer = null
  }
  if (jobRefreshDebounce) {
    clearTimeout(jobRefreshDebounce)
    jobRefreshDebounce = null
  }
})
</script>

<template>
  <div class="result">
    <div class="result__head">
      <PageIntro
        title="Результат обработки"
        subtitle="Транскрипт и отчёт появляются и обновляются по мере обработки записи."
      />
      <div
        v-if="showSuccessBanner"
        class="result__success"
        role="status"
        aria-live="polite"
      >
        <span class="result__success-icon" aria-hidden="true">✓</span>
        <div class="result__success-body">
          <strong class="result__success-title">Обработка завершена</strong>
          <p class="result__success-text">Ниже — ваши транскрипт, отчёт и аудио.</p>
        </div>
      </div>
      <div
        v-if="!loading && !err && job && job.status !== 'done'"
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
    </div>

    <p v-if="loading" class="result__hint">Загрузка…</p>
    <p v-else-if="err" class="result__err">{{ err }}</p>

    <template v-else>
      <div v-if="!job" class="result__banner">
        <span class="result__badge">Нет данных</span>
        Обработка для этой записи ещё не началась или недоступна. Попробуйте загрузить файл снова.
      </div>

      <div v-if="job" class="result__layout">
        <div class="result__main">
          <UiCard title="Транскрипт" class="result__card-priority">
            <TranscriptPanel :segments="segments" :sanitized-text="sanitizedText" />
          </UiCard>

          <UiCard title="Отчёт по удалённым данным" class="result__card-priority">
            <p v-if="stats.length === 0" class="result__hint">
              Появится после поиска персональных данных в тексте: типы данных и примеры маскировки.
            </p>
            <RedactionReport v-else :rows="stats" />
          </UiCard>

          <UiCard title="Аудио">
            <div
              v-if="showTrackSwitch"
              class="result__track-switch"
              role="group"
              aria-label="Версия записи для прослушивания"
            >
              <button
                type="button"
                class="result__track-btn"
                :class="{ 'result__track-btn--on': listenTrack === 'original' }"
                @click="listenTrack = 'original'"
              >
                Исходное
              </button>
              <button
                type="button"
                class="result__track-btn"
                :class="{ 'result__track-btn--on': listenTrack === 'redacted' }"
                @click="listenTrack = 'redacted'"
              >
                Обработанное
              </button>
            </div>
            <AudioPlayerPanel
              :file-name="fileName || 'recording'"
              :duration-sec="durationSec"
              :redactions="timeline"
              :audio-src="playbackUrl"
              :original-download-href="originalDownloadHref"
              :redacted-download-href="redactedDownloadHref"
            />
          </UiCard>
        </div>

        <aside class="result__aside" aria-label="Журнал обработки">
          <div class="result__aside-inner">
            <UiCard title="Журнал обработки" class="result__log-card">
              <ProcessingLogPanel v-if="processingLogEntries.length" :entries="processingLogEntries" />
              <p v-else class="result__log-empty">
                Записи появятся по мере прохождения этапов: загрузка, распознавание, поиск данных, сохранение
                аудио.
              </p>
            </UiCard>
          </div>
        </aside>
      </div>
    </template>

    <div class="result__footer">
      <UiButton type="button" variant="secondary" to="/upload">Новая загрузка</UiButton>
      <UiButton type="button" variant="secondary" @click="router.push('/')">На главную</UiButton>
    </div>
  </div>
</template>

<style scoped>
.result__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem 1.5rem;
  margin-bottom: 0.75rem;
}

.result__head :deep(.intro) {
  margin-bottom: 0;
  flex: 1;
  min-width: 0;
}

@media (max-width: 768px) {
  .result__head {
    flex-direction: column;
    align-items: stretch;
  }
}

.result__success {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  padding: 0.5rem 0.75rem;
  margin-bottom: 0;
  border-radius: var(--radius-sm);
  border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--border));
  background: var(--accent-soft);
  flex-shrink: 0;
  max-width: min(28rem, 46%);
  align-self: flex-start;
}
@media (max-width: 768px) {
  .result__success {
    max-width: none;
    align-self: stretch;
  }
}
.result__success-icon {
  flex-shrink: 0;
  width: 1.35rem;
  height: 1.35rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 0.75rem;
  line-height: 1;
  margin-top: 0.1rem;
}
.result__success-body {
  min-width: 0;
}
.result__success-title {
  display: block;
  font-size: 0.88rem;
  font-weight: 650;
  color: var(--text-strong);
}
.result__success-text {
  margin: 0.2rem 0 0;
  font-size: 0.8rem;
  line-height: 1.4;
  color: var(--text-muted);
}

.result__hint {
  margin: 0 0 1rem;
  color: var(--text-muted);
  font-size: 0.9rem;
}
.result__err {
  color: var(--danger);
  margin: 0 0 1rem;
}
.result__strip {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  padding: 0.5rem 0.65rem;
  margin-bottom: 0;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-muted);
  flex-shrink: 0;
  max-width: min(26rem, 46%);
  align-self: flex-start;
}

@media (max-width: 768px) {
  .result__strip {
    max-width: none;
    align-self: stretch;
  }
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
  background: var(--danger);
}
.result__err-msg {
  font-size: 0.88rem;
  color: var(--danger);
  flex: 1;
  min-width: 0;
}
.result__track-switch {
  display: inline-flex;
  padding: 3px;
  margin-bottom: 0.85rem;
  border-radius: 999px;
  background: var(--bg-muted);
  border: 1px solid var(--border);
  gap: 2px;
}
.result__track-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 0.35rem 0.85rem;
  border-radius: 999px;
  color: var(--text-muted);
  transition:
    background 0.15s,
    color 0.15s;
}
.result__track-btn:hover {
  color: var(--text-strong);
}
.result__track-btn--on {
  background: var(--bg-elevated);
  color: var(--accent);
  box-shadow: var(--shadow-sm);
}

.result__layout {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.result__main {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}

.result__aside {
  min-width: 0;
}

.result__aside-inner {
  min-height: 0;
}

.result__log-empty {
  margin: 0;
  font-size: 0.86rem;
  line-height: 1.5;
  color: var(--text-muted);
}

.result__log-card :deep(.plog__row) {
  grid-template-columns: 1fr;
  gap: 0.35rem;
}

.result__log-card :deep(.plog__badge) {
  justify-self: start;
}

.result__log-card :deep(.plog__msg) {
  grid-column: 1;
}

.result__card-priority {
  scroll-margin-top: 0.5rem;
}

@media (min-width: 1100px) {
  .result__layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
    gap: 1.25rem;
    align-items: start;
  }

  .result__aside-inner {
    position: sticky;
    top: calc(var(--nav-h) + 1.25rem);
    max-height: calc(100svh - var(--nav-h) - 2.5rem);
    overflow-y: auto;
    padding-bottom: 0.25rem;
  }
}

.result__footer {
  margin-top: 1.5rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}
</style>
