import './index.css'
import { isLocalMode } from '@/lib/mode'
import { JudgePage } from '@/pages/JudgePage'
import { DevPage } from '@/pages/DevPage'

export default function App() {
  return isLocalMode() ? <DevPage /> : <JudgePage />
}
