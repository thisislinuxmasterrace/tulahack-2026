/**
 * Формат совпадает с тем, что пишет runner в processing_jobs.processing_events
 * (см. append_event в backend/runner/main.py): массив { ts, level, message }.
 */
import type { ProcessingLogEntry } from '../types/processingLog'

export type { ProcessingLogEntry, ProcessingLogLevel } from '../types/processingLog'

/**
 * Типичная успешная цепочка — те же тексты сообщений, что в runner при обработке задачи.
 */
export const demoProcessingEvents: ProcessingLogEntry[] = [
  {
    ts: '2026-04-18T11:02:03.184729+00:00',
    level: 'info',
    message: 'Задача получена из Redis',
  },
  {
    ts: '2026-04-18T11:02:03.412056+00:00',
    level: 'info',
    message: 'Файл скачан из MinIO, запрос к STT',
  },
  {
    ts: '2026-04-18T11:02:18.903441+00:00',
    level: 'info',
    message: 'STT завершён, запрос к LLM',
  },
  {
    ts: '2026-04-18T11:02:24.551102+00:00',
    level: 'info',
    message: 'LLM завершён, маскировка аудио (redact)',
  },
  {
    ts: '2026-04-18T11:02:41.009883+00:00',
    level: 'info',
    message: 'Обработка завершена (redact аудио в MinIO)',
  },
]
