<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'

import type { TimelineRedaction } from '../../mocks/demoSession'

const props = defineProps<{
  fileName: string
  durationSec: number
  redactions: TimelineRedaction[]
}>()

/** Доля длительности 0..1 для индикатора на шкале (без реального аудио). */
const progress = ref(0.35)
const playing = ref(false)
let raf = 0

const currentLabel = computed(() => formatTime(progress.value * props.durationSec))
const totalLabel = computed(() => formatTime(props.durationSec))

function formatTime(sec: number): string {
  const s = Math.floor(sec % 60)
  const m = Math.floor(sec / 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function tick() {
  if (!playing.value) return
  progress.value = (progress.value + 0.002) % 1
  raf = requestAnimationFrame(tick)
}

function togglePlay() {
  playing.value = !playing.value
  if (playing.value) {
    cancelAnimationFrame(raf)
    tick()
  } else {
    cancelAnimationFrame(raf)
  }
}

onUnmounted(() => cancelAnimationFrame(raf))
</script>

<template>
  <div class="player">
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
    </div>

    <div class="player__timeline-wrap">
      <div class="player__timeline" role="img" aria-label="Разметка редактирования по времени">
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
.player__row {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin-bottom: 1rem;
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
