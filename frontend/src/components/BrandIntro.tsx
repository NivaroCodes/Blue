import { useLayoutEffect, useRef } from 'react'
import { ArrowUpRight } from 'lucide-react'
import { KrakenMark } from './KrakenMark'

const seenKey = 'kraken.intro.seen.v1'

export function shouldShowIntro() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
  try {
    return sessionStorage.getItem(seenKey) !== '1'
  } catch {
    return true
  }
}

export function rememberIntro() {
  try {
    sessionStorage.setItem(seenKey, '1')
  } catch {
    /* Storage restrictions must not block entry. */
  }
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
    const previousOverflow = document.body.style.overflow
    const previousScroll = { left: window.scrollX, top: window.scrollY }
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    element.showModal()
    document.body.style.overflow = 'hidden'
    const finish = () => complete.current()
    const timer = window.setTimeout(finish, reduced.matches ? 1000 : 3300)
    const handleMotionChange = () => {
      if (reduced.matches) finish()
    }
    reduced.addEventListener('change', handleMotionChange)
    return () => {
      clearTimeout(timer)
      reduced.removeEventListener('change', handleMotionChange)
      element.close()
      document.body.style.overflow = previousOverflow
      if (previousFocus?.isConnected && previousFocus !== document.body) previousFocus.focus()
      else document.querySelector<HTMLElement>('#main')?.focus({ preventScroll: true })
      window.scrollTo({ ...previousScroll, behavior: 'instant' })
    }
  }, [active])

  if (!active) return null
  return (
    <dialog
      ref={dialog}
      className="brand-intro"
      aria-labelledby="intro-title"
      aria-describedby="intro-description"
      onCancel={(event) => {
        event.preventDefault()
        onComplete()
      }}
    >
      <div className="intro-topline">
        <span>K / SAFENET KZ</span>
        <span>THREAT INTELLIGENCE</span>
      </div>
      <div className="intro-atmosphere" aria-hidden="true" />
      <div className="intro-center">
        <div className="intro-emblem">
          <div className="intro-orbit" aria-hidden="true" />
          <KrakenMark />
        </div>
        <h1 id="intro-title" className="intro-wordmark" aria-label="Kraken">
          {'KRAKEN'.split('').map((letter, index) => (
            <span
              key={index}
              aria-hidden="true"
              style={{ animationDelay: `${360 + index * 65}ms` }}
            >
              {letter}
            </span>
          ))}
        </h1>
        <p id="intro-description">Видеть глубже. Реагировать раньше.</p>
        <div className="intro-progress" aria-hidden="true">
          <span />
        </div>
      </div>
      <div className="intro-bottomline">
        <span>ОБНАРУЖЕНИЕ ФИНАНСОВЫХ ПИРАМИД</span>
        <button autoFocus onClick={onComplete} className="intro-skip">
          Пропустить <ArrowUpRight size={17} />
        </button>
      </div>
    </dialog>
  )
}
