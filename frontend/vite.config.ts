import { defineConfig, Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

// Serves ../outputs/ at /outputs/ during development
function serveOutputs(): Plugin {
  const outputsDir = path.resolve(__dirname, '..', 'outputs')
  return {
    name: 'serve-outputs',
    configureServer(server) {
      server.middlewares.use('/outputs', (req, res, next) => {
        const urlPath = (req.url ?? '/').replace(/\?.*$/, '')
        const filePath = path.join(outputsDir, urlPath)
        try {
          const stat = fs.statSync(filePath)
          if (stat.isFile()) {
            const ext = path.extname(filePath).toLowerCase()
            if (ext === '.json') res.setHeader('Content-Type', 'application/json')
            else if (ext === '.pdf') res.setHeader('Content-Type', 'application/pdf')
            fs.createReadStream(filePath).pipe(res as NodeJS.WritableStream)
            return
          }
        } catch {
          // not found — fall through
        }
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), serveOutputs()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
