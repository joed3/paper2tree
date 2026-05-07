import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { pdfjs } from 'react-pdf'
import './index.css'
import ExportApp from './ExportApp'

// Inline the pdfjs worker as a blob URL so the export works without a server.
// Vite's ?raw import embeds the worker source directly into the JS bundle.
import pdfjsWorkerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?raw'
const workerBlob = new Blob([pdfjsWorkerSrc], { type: 'application/javascript' })
pdfjs.GlobalWorkerOptions.workerSrc = URL.createObjectURL(workerBlob)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ExportApp />
  </StrictMode>,
)
