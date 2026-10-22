/** Original vector mark. Shared geometry keeps the animated and compact marks identical. */
export function KrakenMark({ className = '' }: { className?: string }) {
  return (
    <svg
      className={`kraken-mark ${className}`}
      viewBox="0 0 128 128"
      fill="none"
      aria-hidden="true"
    >
      <g
        className="kraken-arms"
        stroke="currentColor"
        strokeWidth="8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M46 49C29 53 20 43 20 28M47 59H32C18 59 10 65 10 81M55 64L45 81C40 92 30 98 19 92M61 65V88C61 103 50 111 39 108" />
        <path d="M82 49C99 53 108 43 108 28M81 59H96C110 59 118 65 118 81M73 64L83 81C88 92 98 98 109 92M67 65V88C67 103 78 111 89 108" />
      </g>
      <path
        className="kraken-head"
        fill="currentColor"
        fillRule="evenodd"
        d="M64 8C49 13 38 25 38 40L43 57L55 68H73L85 57L90 40C90 25 79 13 64 8ZM47 41L59 46V52L49 48L47 41ZM81 41L69 46V52L79 48L81 41Z"
        clipRule="evenodd"
      />
    </svg>
  )
}
