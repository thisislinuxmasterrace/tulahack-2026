import type {
  RedactionCategory,
  RedactionStat,
  TimelineRedaction,
  TranscriptSegment,
} from '../mocks/demoSession'

const categoryLabels: Record<string, string> = {
  passport: 'Паспортные данные',
  inn: 'ИНН',
  snils: 'СНИЛС',
  phone: 'Телефон',
  email: 'E-mail',
  address: 'Адрес / принадлежность',
}

export function statusLabelRu(status: string): string {
  const m: Record<string, string> = {
    queued: 'В очереди',
    running: 'Запуск',
    stt: 'Распознавание речи',
    llm: 'Поиск персональных данных',
    render_audio: 'Обработка аудио',
    done: 'Готово',
    failed: 'Ошибка',
    cancelled: 'Отменено',
  }
  return m[status] ?? status
}

/** Пояснение этапа для баннера ожидания. */
export function statusStageHintRu(status: string): string {
  const m: Record<string, string> = {
    queued: 'Запись ждёт своей очереди — обычно это занимает немного времени.',
    running: 'Файл принят, идёт подготовка к распознаванию.',
    stt: 'Распознаётся речь и формируется текст записи.',
    llm: 'Ищутся и скрываются персональные данные в тексте.',
    render_audio: 'Обрабатывается аудио: фрагменты с персональными данными приглушаются или заменяются.',
    done: 'Обработка завершена.',
    failed: 'При обработке произошла ошибка.',
    cancelled: 'Обработка отменена.',
  }
  return m[status] ?? 'Идёт обработка…'
}

/**
 * Текст для вкладки «С персональными данными».
 * Цельный текст из API (transcript_plain / whisper.text) даёт нормальные пробелы;
 * склейка сегментов из массива без разделителя даёт «слово.Слово».
 */
export function segmentsFromJob(whisper: unknown, fallbackPlain: string): TranscriptSegment[] {
  const fromPlain = fallbackPlain.trim()
  if (fromPlain) {
    return [{ text: fromPlain }]
  }
  if (whisper && typeof whisper === 'object') {
    const w = whisper as { text?: string; segments?: Array<{ text?: string }> }
    const t = (w.text ?? '').trim()
    if (t) {
      return [{ text: t }]
    }
    const segs = w.segments
    if (Array.isArray(segs) && segs.length > 0) {
      const joined = segs
        .map((s) => (s.text ?? '').trim())
        .filter(Boolean)
        .join(' ')
      if (joined) {
        return [{ text: joined }]
      }
    }
  }
  return [{ text: '—' }]
}

export function statsFromReport(report: unknown): RedactionStat[] {
  if (!report || typeof report !== 'object') return []
  const r = report as { counts?: Record<string, number>; examples?: Record<string, string[]> }
  const counts = r.counts
  if (!counts || typeof counts !== 'object') return []
  const examples = r.examples ?? {}
  return Object.entries(counts).map(([category, count]) => ({
    category: category as RedactionCategory,
    label: categoryLabels[category] ?? category,
    count,
    examples: examples[category] ?? [],
  }))
}

export function timelineFromReport(report: unknown, durationSec: number): TimelineRedaction[] {
  if (!report || typeof report !== 'object' || durationSec <= 0) return []
  const spans = (report as { spans?: Array<{ type?: string; start_ms?: number; end_ms?: number }> }).spans
  if (!Array.isArray(spans)) return []
  return spans
    .map((s) => {
      const start = ((s.start_ms ?? 0) / 1000 / durationSec) as number
      const end = ((s.end_ms ?? 0) / 1000 / durationSec) as number
      const category = (s.type ?? 'phone') as RedactionCategory
      return { start: Math.min(1, Math.max(0, start)), end: Math.min(1, Math.max(0, end)), category }
    })
    .filter((x) => x.end > x.start)
}

export function durationFromWhisper(whisper: unknown): number {
  if (whisper && typeof whisper === 'object' && 'duration_sec' in whisper) {
    const d = (whisper as { duration_sec?: number }).duration_sec
    if (typeof d === 'number' && d > 0) return d
  }
  return 0
}
