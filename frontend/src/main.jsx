import './cryptoPolyfill.js'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './styles/globals.css'
import App from './App.jsx'
import { useAppStore } from './store/index.js'

// Apply theme to <html> before first paint to avoid FOUC.
useAppStore.getState().initTheme()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
