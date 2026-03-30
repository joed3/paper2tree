import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import ExportApp from './ExportApp'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ExportApp />
  </StrictMode>,
)
