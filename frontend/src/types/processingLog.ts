export type ProcessingLogLevel = 'info' | 'warning' | 'error'

export interface ProcessingLogEntry {
  ts: string
  level: ProcessingLogLevel
  message: string
}
