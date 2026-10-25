import { motion, useReducedMotion } from 'motion/react'
import { ArrowUpRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { levels, levelLabels } from '../lib/model'
import type { Stats } from '../lib/model'

export function RiskSummary({ stats }: { stats: Stats }) {
  const reduce = useReducedMotion()
  return (
    <section className="risk-summary" aria-label="Сводка рисков">
      {levels.map((level, index) => (
        <motion.div
          key={level}
          initial={reduce ? false : { opacity: 0.5, transform: 'translateY(8px)' }}
          animate={{ opacity: 1, transform: 'translateY(0px)' }}
          transition={{ duration: 0.25, delay: index * 0.04, ease: [0.23, 1, 0.32, 1] }}
        >
          <Link
            to={`/?period=all&level=${level}`}
            className={`summary-risk ${level.toLowerCase()}`}
          >
            <div>
              <span>
                <i className={`risk-tick ${level.toLowerCase()}`} />
                {levelLabels[level]} риск
              </span>
              <ArrowUpRight size={16} />
            </div>
            <strong>{stats.by_level[level]}</strong>
            <span>Открыть сообщения</span>
          </Link>
        </motion.div>
      ))}
    </section>
  )
}
