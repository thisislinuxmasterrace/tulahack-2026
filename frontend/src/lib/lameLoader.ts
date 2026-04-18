import lameMinUrl from 'lamejs/lame.min.js?url'

export type Mp3EncoderClass = new (
  channels: number,
  sampleRate: number,
  kbps: number,
) => {
  encodeBuffer(left: Int16Array, right?: Int16Array): Int8Array
  flush(): Int8Array
}

declare global {
  interface Window {
    lamejs?: {
      Mp3Encoder: Mp3EncoderClass
      WavHeader?: unknown
    }
  }
}

let loadPromise: Promise<Mp3EncoderClass> | null = null

/**
 * Модульный вход `lamejs` из npm ломается при сборке Vite/esbuild (ReferenceError: MPEGMode is not defined).
 * Готовый `lame.min.js` — один IIFE; подключаем как классический script → `window.lamejs.Mp3Encoder`.
 */
export function getMp3EncoderClass(): Promise<Mp3EncoderClass> {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('lamejs: only in browser'))
  }
  if (window.lamejs?.Mp3Encoder) {
    return Promise.resolve(window.lamejs.Mp3Encoder)
  }
  if (!loadPromise) {
    loadPromise = new Promise((resolve, reject) => {
      const id = 'lamejs-min-script'
      if (document.getElementById(id)) {
        reject(new Error('lamejs: unexpected script state'))
        return
      }
      const script = document.createElement('script')
      script.id = id
      script.async = true
      script.src = lameMinUrl
      script.onload = () => {
        const ctor = window.lamejs?.Mp3Encoder
        if (typeof ctor !== 'function') {
          reject(new Error('lamejs: Mp3Encoder не найден после загрузки'))
          return
        }
        resolve(ctor)
      }
      script.onerror = () => reject(new Error('lamejs: не удалось загрузить lame.min.js'))
      document.head.appendChild(script)
    })
  }
  return loadPromise
}
