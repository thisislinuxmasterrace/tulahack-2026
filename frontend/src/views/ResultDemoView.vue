<script setup lang="ts">
import AudioPlayerPanel from '../components/audio/AudioPlayerPanel.vue'
import ProcessingLogPanel from '../components/report/ProcessingLogPanel.vue'
import RedactionReport from '../components/report/RedactionReport.vue'
import TranscriptPanel from '../components/transcript/TranscriptPanel.vue'
import PageIntro from '../components/ui/PageIntro.vue'
import UiCard from '../components/ui/UiCard.vue'
import { demoProcessingEvents } from '../mocks/demoProcessingEvents'
import {
  demoDurationSec,
  demoFileName,
  demoRedactionStats,
  demoSanitizedPlain,
  demoTimelineRedactions,
  demoTranscriptSegments,
} from '../mocks/demoSession'
</script>

<template>
  <div class="result">
    <PageIntro
      title="Результат обработки"
      subtitle="Пример того, как выглядит экран после обработки: транскрипт с подсветкой, шкала времени и сводка по найденным данным."
    />

    <div class="result__banner">
      <span class="result__badge">Пример</span>
      Здесь показаны демонстрационные данные, чтобы можно было посмотреть интерфейс без загрузки своего файла.
    </div>

    <div class="result__layout">
      <div class="result__main">
        <UiCard title="Транскрипт">
          <TranscriptPanel :segments="demoTranscriptSegments" :sanitized-text="demoSanitizedPlain" />
        </UiCard>

        <UiCard title="Отчёт по удалённым данным">
          <RedactionReport :rows="demoRedactionStats" />
        </UiCard>

        <UiCard title="Аудио">
          <AudioPlayerPanel
            :file-name="demoFileName"
            :duration-sec="demoDurationSec"
            :redactions="demoTimelineRedactions"
          />
        </UiCard>
      </div>

      <aside class="result__aside" aria-label="Журнал обработки">
        <div class="result__aside-inner">
          <UiCard title="Журнал обработки" class="result__log-card">
            <p class="result__log-hint">
              Пример записей с сервера: когда началась обработка, распознавание речи, поиск данных в тексте и финальное
              сохранение аудио.
            </p>
            <ProcessingLogPanel :entries="demoProcessingEvents" />
          </UiCard>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.result__banner {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  padding: 0.75rem 1rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--accent-soft);
  color: var(--text);
  font-size: 0.88rem;
  line-height: 1.45;
  margin-bottom: 1.5rem;
}

.result__badge {
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 0.2rem 0.45rem;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
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

.result__log-hint {
  margin: 0 0 1rem;
  font-size: 0.88rem;
  color: var(--text-muted);
  line-height: 1.45;
}

</style>
