import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/** Локальная разработка: запросы к `/api` проксируются на шлюз (порт по умолчанию — как у gateway). */
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
