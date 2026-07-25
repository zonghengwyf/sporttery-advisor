import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': resolve(__dirname, 'src') },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://117.72.217.97:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', (err) => console.error('[proxy error]', err.message))
          proxy.on('proxyReq', (_req, req) => console.log('[proxy]', req.method, req.url))
        },
      },
    },
  },
})
