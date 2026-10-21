import { AlertSchema, readStorage, writeStorage } from '../lib/model'
import type { Alert, Review } from '../lib/model'

// Hand-authored synthetic fixtures. Scores illustrate UI states, not model quality.
const samples: [string, number, [string, string][]][] = [
  [
    'Вложи 5 000 ₸ сегодня — получи 10 000 ₸ уже завтра! Доход гарантирован. Пригласи двух друзей и получи бонус. Осталось 3 места.',
    94,
    [
      ['UNREALISTIC_RETURN', 'получи 10 000 ₸ уже завтра'],
      ['MONEY_REQUEST', 'Вложи 5 000 ₸'],
      ['REFERRAL', 'Пригласи двух друзей'],
      ['URGENCY', 'Осталось 3 места'],
    ],
  ],
  [
    'Бүгін 10 000 теңге сал, ертең 20 000 теңге ал! Табысқа кепілдік береміз. Kaspi арқылы жеке картаға аудар.',
    91,
    [
      ['UNREALISTIC_RETURN', 'ертең 20 000 теңге ал'],
      ['GUARANTEED_PROFIT', 'Табысқа кепілдік береміз'],
      ['PERSONAL_TRANSFER', 'жеке картаға аудар'],
    ],
  ],
  [
    'Новая инвестиционная группа: старт от 15 000 тг. За каждого нового участника +20%. Прибыль 200% за неделю, без риска.',
    88,
    [
      ['UNREALISTIC_RETURN', 'Прибыль 200% за неделю'],
      ['REFERRAL', 'За каждого нового участника +20%'],
      ['GUARANTEED_PROFIT', 'без риска'],
    ],
  ],
  [
    'Vlozhi 5000 tg — poluchi 15000 za 2 dnya. Privedi druga i zaberi bonus. Perevod na lichnuyu kartu.',
    85,
    [
      ['UNREALISTIC_RETURN', 'poluchi 15000 za 2 dnya'],
      ['REFERRAL', 'Privedi druga'],
      ['PERSONAL_TRANSFER', 'Perevod na lichnuyu kartu'],
    ],
  ],
  [
    'Только до вечера: вступление в закрытый клуб 30 000 ₸. Выплаты идут из взносов новых участников. Приведите троих.',
    83,
    [
      ['MONEY_REQUEST', 'вступление в закрытый клуб 30 000 ₸'],
      ['REFERRAL', 'Приведите троих'],
      ['URGENCY', 'Только до вечера'],
    ],
  ],
  [
    'Ақшаңды екі есе көбейт! Кіру жарнасы 5 000 теңге. Досыңды шақырсаң, қосымша сыйақы аласың.',
    79,
    [
      ['UNREALISTIC_RETURN', 'Ақшаңды екі есе көбейт'],
      ['MONEY_REQUEST', 'Кіру жарнасы 5 000 теңге'],
      ['REFERRAL', 'Досыңды шақырсаң'],
    ],
  ],
  [
    'Набираем партнёров в проект. Вход 20 000 ₸, вознаграждение за приглашённых. Подробные условия пока не опубликованы.',
    56,
    [
      ['MONEY_REQUEST', 'Вход 20 000 ₸'],
      ['REFERRAL', 'вознаграждение за приглашённых'],
    ],
  ],
  [
    'Пассивный доход каждый день. Напиши куратору, чтобы узнать сумму первого взноса. Условия расскажем в личных сообщениях.',
    48,
    [['MONEY_REQUEST', 'сумму первого взноса']],
  ],
  [
    'Жаңа жобаға серіктестер іздейміз. Қатысу үшін жарна қажет. Табыстылық туралы толық ақпарат кейін болады.',
    43,
    [['MONEY_REQUEST', 'Қатысу үшін жарна қажет']],
  ],
  [
    'Инвестиционный клуб проводит платную встречу. Обсудим стратегии и риски. Что входит в стоимость, уточняйте у организатора.',
    32,
    [['MONEY_REQUEST', 'платную встречу']],
  ],
  [
    'Ищем амбассадоров сервиса. Есть бонус за регистрацию друзей, но выплата требует проверки условий программы.',
    37,
    [['REFERRAL', 'бонус за регистрацию друзей']],
  ],
  [
    'Бесплатная лекция о финансовой грамотности в субботу. Разберём риски и принципы диверсификации. Взносы не нужны.',
    7,
    [],
  ],
  [
    'Достар, қаржылық сауаттылық сабағы тегін өтеді. Ешқандай ақша салудың қажеті жоқ. Барлық сұрақты талқылаймыз.',
    5,
    [],
  ],
  [
    'Напоминание: стоимость инвестиций может снижаться. Прошлая доходность не гарантирует будущую. Изучайте документы.',
    4,
    [],
  ],
  [
    'Собираемся на волонтёрскую встречу в воскресенье. Участие бесплатное, регистрация открыта для всех.',
    2,
    [],
  ],
  ['Кітап клубының кездесуі ертең сағат 18:00-де. Кіру тегін. Достарыңды шақыр!', 3, []],
  [
    'Курс по планированию личного бюджета. Стоимость обучения 8 000 тг. Прибыль и заработок не обещаем.',
    12,
    [],
  ],
  [
    'Спасибо за встречу! Презентацию о распознавании финансовых пирамид отправим в этот чат завтра.',
    1,
    [],
  ],
]
const chats = [
  { id: 'tg_growth', name: 'Финансовый рост KZ', platform: 'telegram' as const },
  { id: 'tg_invest', name: 'Инвестиции · Шымкент', platform: 'telegram' as const },
  { id: 'wa_income', name: 'Табыс / Доход', platform: 'whatsapp' as const },
  { id: 'tg_finlit', name: 'Финансовая грамотность', platform: 'telegram' as const },
  { id: 'wa_community', name: 'Қауымдастық KZ', platform: 'whatsapp' as const },
]
const baseTime = Date.now()
function createSample(index: number, live = false): Alert {
  const sampleIndex = index % samples.length
  const [text, score, reasons] = samples[sampleIndex]
  const chat =
    chats[
      sampleIndex < 6
        ? sampleIndex % 3
        : sampleIndex < 11
          ? (sampleIndex + 1) % 3
          : 3 + (sampleIndex % 2)
    ]
  const risk_level = score >= 60 ? 'HIGH' : score >= 30 ? 'MEDIUM' : 'LOW'
  return AlertSchema.parse({
    id: live ? `demo-live-${index}` : `demo-${index + 1}`,
    platform: chat.platform,
    chat_id: chat.id,
    chat_name: chat.name,
    message_id: `msg_${1000 + index}`,
    sender_hash: `user_hash_${String(index + 11).padStart(3, '0')}`,
    text,
    timestamp: new Date(live ? Date.now() : baseTime - index * 29 * 60_000).toISOString(),
    status: 'PROCESSED',
    risk_score: score,
    risk_level,
    reasons: reasons.map(([code, evidence]) => ({ code, evidence })),
    explanation:
      score >= 60
        ? 'Совокупность признаков: обещание быстрой прибыли, запрос вложений или зависимость выплат от привлечения участников. Нужна проверка контекста аналитиком.'
        : score >= 30
          ? 'Есть отдельные признаки, требующие уточнения. Сообщение не содержит достаточно контекста для высокой оценки риска. Проверьте условия участия и источник выплат.'
          : 'Выраженных признаков пирамидальной схемы в этом сообщении не обнаружено. Низкий риск не является гарантией безопасности.',
    confidence: score >= 60 ? 0.89 : score >= 30 ? 0.66 : 0.93,
    review_status: [12, 13, 16].includes(index)
      ? 'REVIEWED'
      : index === 9
        ? 'FALSE_POSITIVE'
        : 'NEW',
    reviewer_note:
      index === 9 ? 'Учебный пример: оплата за мероприятие, обещаний доходности нет.' : '',
    model_version: 'synthetic-fixtures-v1',
  })
}
const initial: Alert[] = Array.from({ length: 28 }, (_, i) => createSample(i))
initial.push(
  ...(['PENDING', 'PROCESSING', 'ERROR'] as const).map((status, i) => ({
    ...createSample(28 + i),
    id: `demo-pipeline-${i}`,
    status,
    risk_score: null,
    risk_level: null,
    confidence: null,
    reasons: [],
    explanation: '',
    review_status: 'NEW' as const,
  })),
)
let feed: Alert[] = []
let nextLive = 0
export function demoAlerts(): Alert[] {
  const raw = readStorage<unknown>('blue.demo.reviews.v1', {})
  const reviews =
    typeof raw === 'object' && raw !== null
      ? (raw as Record<string, { status: Review; note: string }>)
      : {}
  return [...feed, ...initial].map((a) => {
    const review = reviews[a.id]
    return review && ['NEW', 'REVIEWED', 'FALSE_POSITIVE'].includes(review.status)
      ? { ...a, review_status: review.status, reviewer_note: review.note }
      : a
  })
}
export function addDemoAlert() {
  const alert = createSample(nextLive++, true)
  feed = [alert, ...feed].slice(0, 100)
  return alert
}
export function reviewDemo(id: string, status: Review, note: string) {
  const previous = readStorage<Record<string, unknown>>('blue.demo.reviews.v1', {})
  writeStorage('blue.demo.reviews.v1', { ...previous, [id]: { status, note } })
  return demoAlerts().find((a) => a.id === id)!
}
