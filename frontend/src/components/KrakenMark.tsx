/** Abstract mantle and folded tentacles; no face or mascot details. */
export function KrakenMark({ className = '' }: { className?: string }) {
  return (
    <svg className={`kraken-mark ${className}`} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <path
        className="mark-mantle"
        d="M24 3 34 13 32 23 24 28 16 23 14 13 24 3Z"
        fill="currentColor"
      />
      <g className="mark-tentacles" stroke="currentColor" strokeWidth="4" strokeLinejoin="miter">
        <path d="M18 22 10 28H3V36H10M30 22 38 28H45V36H38M21 26V35L13 43H5M27 26V35L35 43H43" />
      </g>
    </svg>
  )
}
