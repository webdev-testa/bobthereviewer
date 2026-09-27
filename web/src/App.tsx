import { TooltipProvider } from '@/components/ui/tooltip'
import { isLocalMode } from '@/lib/mode'
import { JudgePage } from '@/pages/JudgePage'
import { DevPage } from '@/pages/DevPage'

export default function App() {
  return <TooltipProvider>{isLocalMode() ? <DevPage /> : <JudgePage />}</TooltipProvider>
}
