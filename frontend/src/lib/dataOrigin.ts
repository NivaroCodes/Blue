import type { Alert } from './model'

/** Explicit seed provenance, not a fuzzy search for words in ordinary messages. */
export function isSyntheticAlert(alert: Alert): boolean {
  return (
    alert.is_synthetic === true ||
    alert.chat_id === 'blue_demo_synthetic_v1' ||
    /^synthetic-v\d+-\d+$/.test(alert.message_id) ||
    alert.text.trimStart().startsWith('[SYNTHETIC / ВЫМЫШЛЕННЫЕ ДАННЫЕ]')
  )
}
