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

    <div class="result__grid">
      <UiCard title="Аудио" class="result__span2">
        <AudioPlayerPanel
          :file-name="demoFileName"
          :duration-sec="demoDurationSec"
          :redactions="demoTimelineRedactions"
        />
      </UiCard>

      <UiCard title="Транскрипт" class="result__span2">
        <TranscriptPanel :segments="demoTranscriptSegments" :sanitized-text="demoSanitizedPlain" />
      </UiCard>

      <UiCard title="Отчёт по удалённым данным" class="result__span2">
        <RedactionReport :rows="demoRedactionStats" />
      </UiCard>

      <UiCard title="Журнал обработки" class="result__span2">
        <p class="result__log-hint">
          Пример записей с сервера: когда началась обработка, распознавание речи, поиск данных в тексте и финальное
          сохранение аудио. Время показано в UTC.
        </p>
        <ProcessingLogPanel :entries="demoProcessingEvents" />
      </UiCard>
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

.result__grid {
  display: grid;
  gap: 1.25rem;
}

@media (min-width: 900px) {
  .result__grid {
    grid-template-columns: 1fr 1fr;
  }

  .result__span2 {
    grid-column: span 2;
  }
}

.result__log-hint {
  margin: 0 0 1rem;
  font-size: 0.88rem;
  color: var(--text-muted);
  line-height: 1.45;
}

</style>
