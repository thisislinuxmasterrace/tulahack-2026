<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'

import type { TimelineRedaction } from '../../types/result'

const props = defineProps<{
  fileName: string
  durationSec: number
  redactions: TimelineRedaction[]
  audioSrc?: string | null
  /** Ссылки с `?access_token=` и `download=1` для сохранения файла. */
  originalDownloadHref?: string | null
  redactedDownloadHref?: string | null
}>()

function safeBaseName(name: string): string {
  const t = name.trim() || 'audio'
  return t.replace(/[\\/:*?"<>|]+/g, '_')
}

function originalDownloadName(): string {
  const base = safeBaseName(props.fileName)
  return /\.mp3$/i.test(base) ? base : `${base}.mp3`
}

function redactedDownloadName(): string {
  const base = safeBaseName(props.fileName)
  const m = base.match(/^(.*)(\.[^.]+)$/)
  const stem = m ? m[1] : base
  const ext = m ? m[2] : '.mp3'
  return `redacted_${stem}${ext}`
}

const showDownloads = computed(
  () =>
    !!(props.originalDownloadHref?.length || props.redactedDownloadHref?.length),
)

const audioRef = ref<HTMLAudioElement | null>(null)
/** Safari часто не играет потоковый MP3 с API; после ошибки подставляем blob URL. */
const blobSrc = ref<string | null>(null)
const blobFallbackTried = ref(false)
/** Один проход HEAD+fetch для Safari (малые файлы). */
const safariSmallPrefetchDone = ref(false)
const playbackError = ref<string | null>(null)

const SAFARI_BLOB_PREFETCH_MAX = 8 * 1024 * 1024

function isSafari(): boolean {
  const ua = navigator.userAgent
  return /safari/i.test(ua) && !/chrome|crios|chromium|android|edg/i.test(ua)
}

function looksLikeAudioResponse(res: Response): boolean {
  const ct = (res.headers.get('content-type') || '').toLowerCase()
  if (ct.includes('json') || ct.includes('text/html')) {
    return false
  }
  return (
    !ct ||
    ct.includes('audio') ||
    ct.includes('mpeg') ||
    ct.includes('octet-stream')
  )
}

const mediaDurationSec = ref(0)
const progress = ref(0)
const playing = ref(false)
let raf = 0

const live = computed(() => !!(props.audioSrc && props.audioSrc.length > 0))

const effectiveAudioSrc = computed(() => blobSrc.value ?? props.audioSrc ?? undefined)

const currentLabel = computed(() => {
  const dur = effectiveDuration.value
  if (dur <= 0) return formatTime(0)
  return formatTime(progress.value * dur)
})
const totalLabel = computed(() => {
  const dur = effectiveDuration.value
  if (dur <= 0) return '—'
  return formatTime(dur)
})

/** До появления метаданных у `<audio>` — длительность из STT; затем длительность из файла (MP3). */
const effectiveDuration = computed(() => {
  if (mediaDurationSec.value > 0) {
    return mediaDurationSec.value
  }
  if (props.durationSec > 0) {
    return props.durationSec
  }
  return 0
})

function syncDurationFromElement() {
  const el = audioRef.value
  if (!el) return
  const d = el.duration
  if (typeof d === 'number' && !Number.isNaN(d) && d > 0 && d !== Number.POSITIVE_INFINITY) {
    mediaDurationSec.value = d
  }
}

function formatTime(sec: number): string {
  const s = Math.floor(sec % 60)
  const m = Math.floor(sec / 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function tickMock() {
  if (!playing.value) return
  progress.value = (progress.value + 0.002) % 1
  raf = requestAnimationFrame(tickMock)
}

async function togglePlay() {
  if (live.value) {
    const el0 = audioRef.value
    if (!el0) return
    if (!el0.paused) {
      el0.pause()
      return
    }
    await ensureSafariPlayableBlobIfSmall()
    await nextTick()
    const el = audioRef.value
    if (!el) return
    const p = el.play()
    if (p !== undefined) {
      void p.catch(() => {
        playing.value = false
      })
    }
  } else {
    playing.value = !playing.value
    if (playing.value) {
      cancelAnimationFrame(raf)
      tickMock()
    } else {
      cancelAnimationFrame(raf)
    }
  }
}

function onTimeUpdate() {
  const el = audioRef.value
  if (!el) return
  let dur = effectiveDuration.value
  if (typeof el.duration === 'number' && !Number.isNaN(el.duration) && el.duration > 0) {
    dur = el.duration
  }
  if (dur <= 0) return
  if (mediaDurationSec.value <= 0) {
    syncDurationFromElement()
  }
  progress.value = Math.min(1, el.currentTime / dur)
}

function onLoadedMetadata() {
  syncDurationFromElement()
  const el = audioRef.value
  if (el) {
    const dur = effectiveDuration.value
    if (dur > 0) {
      progress.value = Math.min(1, el.currentTime / dur)
    }
  }
}

function onDurationChange() {
  syncDurationFromElement()
}

function onPlay() {
  playing.value = true
}

function onPause() {
  playing.value = false
}

function onEnded() {
  playing.value = false
  progress.value = 0
}

function revokeBlobIfAny() {
  if (blobSrc.value) {
    URL.revokeObjectURL(blobSrc.value)
    blobSrc.value = null
  }
}

async function ensureSafariPlayableBlobIfSmall() {
  const src = props.audioSrc
  if (!isSafari() || blobSrc.value || !src || safariSmallPrefetchDone.value) {
    return
  }
  safariSmallPrefetchDone.value = true
  try {
    const head = await fetch(src, { method: 'HEAD' })
    if (!head.ok) {
      return
    }
    if (!looksLikeAudioResponse(head)) {
      return
    }
    const cl = parseInt(head.headers.get('content-length') || '', 10)
    if (!Number.isFinite(cl) || cl > SAFARI_BLOB_PREFETCH_MAX) {
      return
    }
    const res = await fetch(src)
    if (!res.ok || !looksLikeAudioResponse(res)) {
      return
    }
    const blob = await res.blob()
    revokeBlobIfAny()
    blobSrc.value = URL.createObjectURL(blob)
    await nextTick()
    audioRef.value?.load()
  } catch {
    /* остаёмся на потоковом URL; сработает tryBlobFallbackAfterError при error */
  }
}

async function tryBlobFallbackAfterError() {
  const src = props.audioSrc
  if (!src || blobSrc.value || blobFallbackTried.value) {
    return
  }
  blobFallbackTried.value = true
  try {
    const res = await fetch(src)
    if (!res.ok) {
      playbackError.value = `Не удалось загрузить аудио (${res.status}).`
      return
    }
    if (!looksLikeAudioResponse(res)) {
      playbackError.value = 'Сервер вернул не аудио — проверьте вход или скачайте файл.'
      return
    }
    const blob = await res.blob()
    revokeBlobIfAny()
    blobSrc.value = URL.createObjectURL(blob)
    await nextTick()
    const el = audioRef.value
    if (!el) return
    el.load()
    const p = el.play()
    if (p !== undefined) void p.catch(() => {})
  } catch {
    playbackError.value = 'Не удалось воспроизвести. Попробуйте скачать файл.'
  }
}

function onAudioError() {
  const el = audioRef.value
  const code = el?.error?.code
  const msg = el?.error?.message
  if (import.meta.env.DEV) {
    console.warn('[AudioPlayer] error', code, msg)
  }
  if (blobSrc.value) {
    playbackError.value = 'Не удалось воспроизвести. Скачайте файл по ссылке ниже.'
    return
  }
  playbackError.value = null
  void tryBlobFallbackAfterError()
}

function seekClientX(clientX: number, el: HTMLElement) {
  const rect = el.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  progress.value = ratio
  const a = audioRef.value
  let dur = effectiveDuration.value
  if (a && typeof a.duration === 'number' && !Number.isNaN(a.duration) && a.duration > 0) {
    dur = a.duration
  }
  if (!live.value || !a || dur <= 0) {
    return
  }
  let t = ratio * dur
  if (
    typeof a.duration === 'number' &&
    !Number.isNaN(a.duration) &&
    a.duration > 0 &&
    t > a.duration
  ) {
    t = a.duration
  }
  a.currentTime = t
}

function onTimelinePointerDown(e: PointerEvent) {
  const target = e.currentTarget as HTMLElement
  target.setPointerCapture(e.pointerId)
  seekClientX(e.clientX, target)
}

function onTimelinePointerMove(e: PointerEvent) {
  const target = e.currentTarget as HTMLElement
  if (!target.hasPointerCapture(e.pointerId)) return
  seekClientX(e.clientX, target)
}

watch(
  () => props.audioSrc,
  async () => {
    playbackError.value = null
    blobFallbackTried.value = false
    safariSmallPrefetchDone.value = false
    revokeBlobIfAny()
    playing.value = false
    progress.value = 0
    mediaDurationSec.value = 0
    cancelAnimationFrame(raf)
    await nextTick()
    audioRef.value?.load()
  },
)

onUnmounted(() => {
  cancelAnimationFrame(raf)
  revokeBlobIfAny()
})
</script>

<template>
  <div class="player">
    <audio
      v-if="live"
      :key="`${audioSrc ?? ''}|${blobSrc ? 'b' : 'd'}`"
      ref="audioRef"
      class="player__audio"
      :src="effectiveAudioSrc"
      preload="auto"
      playsinline
      webkit-playsinline
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoadedMetadata"
      @durationchange="onDurationChange"
      @play="onPlay"
      @pause="onPause"
      @ended="onEnded"
      @error="onAudioError"
    />

    <p v-if="playbackError" class="player__err" role="alert">{{ playbackError }}</p>

    <div class="player__row">
      <button type="button" class="player__play" :aria-pressed="playing" @click="togglePlay">
        <span class="sr-only">{{ playing ? 'Пауза' : 'Воспроизвести' }}</span>
        <svg v-if="!playing" width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="currentColor" d="M8 5v14l11-7z" />
        </svg>
        <svg v-else width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="currentColor" d="M6 5h4v14H6V5zm8 0h4v14h-4V5z" />
        </svg>
      </button>
      <div class="player__meta">
        <span class="player__name">{{ fileName }}</span>
        <span class="player__time">{{ currentLabel }} / {{ totalLabel }}</span>
      </div>

      <div v-if="showDownloads" class="player__downloads" role="group" aria-label="Скачать аудио">
        <a
          v-if="originalDownloadHref"
          class="player__dl"
          :href="originalDownloadHref"
          :download="originalDownloadName()"
          :title="`Скачать исходное: ${originalDownloadName()}`"
        >
          <span class="player__dl-icon" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 3v12m0 0l4-4m-4 4L8 11M4 21h16" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
          <span class="player__dl-text">Исходное</span>
        </a>
        <a
          v-if="redactedDownloadHref"
          class="player__dl player__dl--accent"
          :href="redactedDownloadHref"
          :download="redactedDownloadName()"
          :title="`Скачать обработанное: ${redactedDownloadName()}`"
        >
          <span class="player__dl-icon" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 3v12m0 0l4-4m-4 4L8 11M4 21h16" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
          <span class="player__dl-text">Обработанное</span>
        </a>
      </div>
    </div>

    <div class="player__timeline-wrap">
      <div
        class="player__timeline"
        role="slider"
        :aria-valuemin="0"
        :aria-valuemax="100"
        :aria-valuenow="Math.round(progress * 100)"
        aria-label="Позиция воспроизведения"
        tabindex="0"
        @pointerdown="onTimelinePointerDown"
        @pointermove="onTimelinePointerMove"
      >
        <div
          v-for="(z, i) in redactions"
          :key="i"
          class="player__zone"
          :style="{
            left: `${z.start * 100}%`,
            width: `${(z.end - z.start) * 100}%`,
          }"
          :title="z.category"
        />
        <div class="player__playhead" :style="{ left: `${progress * 100}%` }" />
      </div>
      <div class="player__legend">
        <span class="player__dot player__dot--redact" /> фрагменты с скрытыми данными
      </div>
    </div>
  </div>
</template>

<style scoped>
/* WebKit: не используем clip/overflow:hidden на <audio> — иногда глушит вывод. */
.player__audio {
  position: fixed;
  left: 0;
  bottom: 0;
  width: 2px;
  height: 2px;
  z-index: -1;
  opacity: 0.02;
  pointer-events: none;
}

.player__err {
  margin: 0 0 0.75rem;
  font-size: 0.82rem;
  color: var(--danger, #b42318);
  line-height: 1.4;
}

.player__row {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

.player__downloads {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  margin-left: auto;
}

.player__dl {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.38rem 0.72rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  text-decoration: none;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-strong);
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s;
  white-space: nowrap;
}

.player__dl:hover {
  background: var(--bg-muted);
  border-color: var(--border-strong);
  text-decoration: none;
}

.player__dl--accent {
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  background: var(--accent-soft);
  color: var(--accent);
}

.player__dl--accent:hover {
  background: color-mix(in srgb, var(--accent) 18%, var(--bg-elevated));
  border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
}

.player__dl-icon {
  display: flex;
  opacity: 0.9;
}

.player__dl-text {
  max-width: 11rem;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 520px) {
  .player__downloads {
    margin-left: 0;
    width: 100%;
    justify-content: flex-start;
  }
}

.player__play {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--accent);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition:
    background 0.15s,
    border-color 0.15s;
}

.player__play:hover {
  background: var(--accent-soft);
  border-color: var(--accent);
}

.player__play:focus-visible {
  outline: 2px solid var(--accent-ring);
  outline-offset: 2px;
}

.player__meta {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.player__name {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text-strong);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.player__time {
  font-family: var(--font-mono);
  font-size: 0.78rem;
  color: var(--text-muted);
}

.player__timeline-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.player__timeline {
  position: relative;
  height: 36px;
  border-radius: 8px;
  background: var(--bg-muted);
  border: 1px solid var(--border);
  overflow: hidden;
  touch-action: none;
  cursor: pointer;
}

.player__timeline:focus-visible {
  outline: 2px solid var(--accent-ring);
  outline-offset: 2px;
}

.player__zone {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--timeline-redact);
  border-left: 1px solid var(--danger-border);
  border-right: 1px solid var(--danger-border);
  pointer-events: none;
}

.player__playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  margin-left: -1px;
  background: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--bg-elevated) 50%, transparent);
  pointer-events: none;
}

.player__legend {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.player__dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.player__dot--redact {
  background: var(--timeline-redact);
  border: 1px solid var(--danger-border);
}
</style>
