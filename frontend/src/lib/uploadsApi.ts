import { apiFetch, clearTokens, getAccessToken, type ApiError } from './auth'

export type UploadWithQueueResponse = {
  upload: {
    id: string
    storage_url: string
    original_filename: string
    byte_size: number
    created_at: string
    content_type?: string
  }
  processing_job?: {
    id: string
    status: string
  }
  queue: {
    enqueued: boolean
    queue_key?: string
    reason?: string
    error?: string
  }
}

export type UploadDTO = {
  id: string
  user_id: string
  bucket: string
  object_key: string
  storage_url: string
  original_filename: string
  content_type: string
  byte_size: number
  created_at: string
}

export type ProcessingJobDetail = {
  id: string
  upload_id: string
  status: string
  stage?: string
  error_code?: string
  error_message?: string
  whisper_model?: string
  llm_model?: string
  whisper_output?: unknown
  llm_entities?: unknown
  transcript_plain?: string
  transcript_redacted?: string
  redaction_report?: unknown
  processing_events?: unknown
  redacted_audio_storage_url?: string
  created_at: string
  updated_at: string
  started_at?: string
  finished_at?: string
}

/** Краткий статус для опроса: из Redis или из БД. */
export type ProcessingPollStatus = {
  upload_id: string
  processing_job_id: string | null
  status: string
  terminal: boolean
  from_cache: boolean
  at?: string
  error_message?: string
  processing_absent?: boolean
}

export async function fetchProcessingStatus(uploadId: string): Promise<ProcessingPollStatus> {
  const res = await apiFetch(`/uploads/${uploadId}/processing-status`)
  const data = await res.json().catch(() => ({}))
  if (res.status === 401) {
    clearTokens()
    throw new Error('Сессия истекла — войдите снова')
  }
  if (res.status === 404) {
    throw new Error('Загрузка не найдена')
  }
  if (!res.ok) {
    const err = data as ApiError
    throw new Error(err.error?.message ?? res.statusText)
  }
  return data as ProcessingPollStatus
}

/**
 * Поток статуса по WebSocket: первое сообщение — как у fetchProcessingStatus, далее — push из Redis.
 * Токен передаётся в query (access_token): для WS заголовок Authorization не используется.
 */
export function connectProcessingStatusStream(
  uploadId: string,
  onStatus: (s: ProcessingPollStatus) => void,
  onTransportError?: () => void,
): () => void {
  const token = getAccessToken()
  if (!token) {
    onTransportError?.()
    throw new Error('Нужна авторизация')
  }
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const q = new URLSearchParams({ access_token: token })
  const url = `${wsProto}//${window.location.host}/api/v1/uploads/${encodeURIComponent(uploadId)}/processing-stream?${q.toString()}`
  const ws = new WebSocket(url)
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data as string) as ProcessingPollStatus
      onStatus(data)
    } catch {}
  }
  ws.onerror = () => {
    onTransportError?.()
  }
  return () => {
    ws.close()
  }
}

export async function fetchUploadDetail(uploadId: string): Promise<{
  upload: UploadDTO
  processing_job: ProcessingJobDetail | null
}> {
  const res = await apiFetch(`/uploads/${uploadId}`)
  const data = await res.json().catch(() => ({}))
  if (res.status === 401) {
    clearTokens()
    throw new Error('Сессия истекла — войдите снова')
  }
  if (res.status === 404) {
    throw new Error('Загрузка не найдена')
  }
  if (!res.ok) {
    const err = data as ApiError
    throw new Error(err.error?.message ?? res.statusText)
  }
  return data as { upload: UploadDTO; processing_job: ProcessingJobDetail | null }
}

/** Загрузка аудиофайла на шлюз (multipart); требуется сессия. */
export async function uploadAudio(file: File): Promise<UploadWithQueueResponse> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await apiFetch('/uploads', {
    method: 'POST',
    body: fd,
  })
  const data = await res.json().catch(() => ({}))
  if (res.status === 401) {
    clearTokens()
    throw new Error('Сессия истекла — войдите снова')
  }
  if (!res.ok) {
    const err = data as ApiError
    throw new Error(err.error?.message ?? res.statusText)
  }
  return data as UploadWithQueueResponse
}
