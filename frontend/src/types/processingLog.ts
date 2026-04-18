/** Совпадает с элементами массива processing_events из API (runner append_event). */
export type ProcessingLogLevel = 'info' | 'warning' | 'error'

export interface ProcessingLogEntry {
  /** ISO 8601, UTC */
  ts: string
  level: ProcessingLogLevel
  message: string
}
