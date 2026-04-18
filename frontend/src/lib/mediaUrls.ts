import { getAccessToken } from './auth'

const apiBase = '/api/v1'

export function uploadOriginalStreamUrl(
  uploadId: string,
  opts?: { download?: boolean },
): string {
  const q = new URLSearchParams()
  const token = getAccessToken()
  if (token) q.set('access_token', token)
  if (opts?.download) q.set('download', '1')
  const qs = q.toString()
  return `${apiBase}/uploads/${encodeURIComponent(uploadId)}/original${qs ? `?${qs}` : ''}`
}

export function uploadRedactedStreamUrl(
  uploadId: string,
  opts?: { download?: boolean },
): string {
  const q = new URLSearchParams()
  const token = getAccessToken()
  if (token) q.set('access_token', token)
  if (opts?.download) q.set('download', '1')
  const qs = q.toString()
  return `${apiBase}/uploads/${encodeURIComponent(uploadId)}/redacted-audio${qs ? `?${qs}` : ''}`
}
