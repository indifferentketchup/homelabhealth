import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { detectMode } from '@/mode.js'
import {
  PATH_808NOTES_HOME,
  PATH_BOOLAB_HOME,
  PATH_BOOOPS_HOME,
} from '@/routes/paths.js'

export function RootRedirect() {
  const navigate = useNavigate()
  useEffect(() => {
    const mode = detectMode()
    const pathMap = {
      booops: PATH_BOOOPS_HOME,
      '808notes': PATH_808NOTES_HOME,
      boolab: PATH_BOOLAB_HOME,
    }
    navigate(pathMap[mode] || PATH_BOOLAB_HOME, { replace: true })
  }, [navigate])
  return null
}
