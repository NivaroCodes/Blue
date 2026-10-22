import { useLayoutEffect, useRef } from 'react'
import { ArrowRight } from 'lucide-react'
import { KrakenMark } from './KrakenMark'

// Every full page entry gets the entrance. SPA navigation never replays it.
export function shouldShowIntro() {
  return true
}

export function BrandIntro({ active, onComplete }: { active: boolean; onComplete: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const complete = useRef(onComplete)
  complete.current = onComplete
  useLayoutEffect(() => {
    if (!active) return
    const element = dialog.current!
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overflow = document.body.style.overflow
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    element.showModal()
    document.body.style.overflow = 'hidden'
    const timer = window.setTimeout(() => complete.current(), reduced.matches ? 650 : 2100)
    const motionChange = () => {
      if (reduced.matches) complete.current()
    }
    reduced.addEventListener('change', motionChange)
    return () => {
      clearTimeout(timer)
      reduced.removeEventListener('change', motionChange)
      element.close()
      document.body.style.overflow = overflow
      if (previousFocus?.isConnected && previousFocus !== document.body)
        previousFocus.focus({ preventScroll: true })
      else document.querySelector<HTMLElement>('#main')?.focus({ preventScroll: true })
    }
  }, [active])
  if (!active) return null
  return (
    <dialog
      ref={dialog}
      className="brand-intro"
      aria-labelledby="intro-title"
      onCancel={(e) => {
        e.preventDefault()
        onComplete()
      }}
    >
      <span className="intro-corner">Kraken / SafeNet KZ</span>
      <div className="intro-center">
        <div className="intro-symbol">
          <KrakenMark />
        </div>
        <h1 id="intro-title" className="intro-wordmark" aria-label="Kraken">
          {'KRAKEN'.split('').map((letter, i) => (
            <span className="intro-letter-mask" key={i} aria-hidden="true">
              <span style={{ animationDelay: `${180 + i * 65}ms` }}>{letter}</span>
            </span>
          ))}
        </h1>
        <p>Сигналы. Контекст. Решение.</p>
      </div>
      <button autoFocus className="intro-skip" onClick={onComplete}>
        Пропустить <ArrowRight size={16} />
      </button>
    </dialog>
  )
}
