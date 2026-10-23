import json
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

from .models import init_db, MessageRecord, AnalysisRecord, ReviewRecord, EntityRecord, make_message_pk


# Comprehensive, diverse real-world scenarios:
# Structure: (msg_id, platform, chat_id, chat_name, chat_url, sender_hash, text, minutes_ago)
SCENARIOS = [
    # ═══════════════════════════════════════════════════════════════
    # CLUSTER A: Serial Bot Broadcasting Wave ("bot_quick_kzt")
    # Broadcasts identical scam message across 3 different communities
    # ═══════════════════════════════════════════════════════════════
    (
        "msg_bot_01",
        "telegram",
        "tg_growth",
        "Финансовый рост KZ",
        "https://t.me/fin_growth_kz",
        "bot_quick_kzt",
        "Вложи 5 000 ₸ сегодня — получи 10 000 ₸ уже завтра! Доход гарантирован. Пригласи двух друзей и получи бонус. Осталось 3 места.",
        180,
    ),
    (
        "msg_bot_02",
        "telegram",
        "tg_invest",
        "Инвестиции · Шымкент",
        "https://t.me/invest_shymkent",
        "bot_quick_kzt",
        "Вложи 5 000 ₸ сегодня — получи 10 000 ₸ уже завтра! Доход гарантирован. Пригласи двух друзей и получи бонус. Осталось 3 места.",
        120,
    ),
    (
        "msg_bot_03",
        "whatsapp",
        "wa_income",
        "Табыс / Доход",
        "https://chat.whatsapp.com/tabys_income_kz",
        "bot_quick_kzt",
        "Вложи 5 000 ₸ сегодня — получи 10 000 ₸ уже завтра! Доход гарантирован. Пригласи двух друзей и получи бонус. Осталось 3 места.",
        60,
    ),
    # 4th message from same bot with slight variant
    (
        "msg_bot_04",
        "telegram",
        "tg_crypto_hub",
        "Крипто Клуб Алматы",
        "https://t.me/crypto_almaty_hub",
        "bot_quick_kzt",
        "Срочный набор в закрытый пул! Депозит 10 000 ₸, завтра возврат 25 000 ₸. Перевод на Kaspi. Успей зайти!",
        10,
    ),

    # ═══════════════════════════════════════════════════════════════
    # CLUSTER B: Kazakh Language Pyramids (Kaspi card P2P, multiplier)
    # ═══════════════════════════════════════════════════════════════
    (
        "msg_kz_01",
        "whatsapp",
        "wa_income",
        "Табыс / Доход",
        "https://chat.whatsapp.com/tabys_income_kz",
        "user_kz_promoter",
        "Бүгін 10 000 теңге сал, ертең 20 000 теңге ал! Табысқа кепілдік береміз. Kaspi арқылы жеке картаға аудар.",
        160,
    ),
    (
        "msg_kz_02",
        "telegram",
        "tg_invest",
        "Инвестиции · Шымкент",
        "https://t.me/invest_shymkent",
        "user_kz_promoter",
        "Ақшаңды екі есе көбейт! Кіру жарнасы 5 000 теңге. Досыңды шақырсаң, қосымша сыйақы аласың.",
        140,
    ),
    (
        "msg_kz_03",
        "whatsapp",
        "wa_income",
        "Табыс / Доход",
        "https://chat.whatsapp.com/tabys_income_kz",
        "user_kz_matrix",
        "Жаңа қаржылық айналым: 15 000 теңге сал да, ертең 45 000 теңге ал. 100% кепілдік береміз. Тәуекелсіз табыс!",
        130,
    ),
    (
        "msg_kz_04",
        "telegram",
        "tg_invest",
        "Инвестиции · Шымкент",
        "https://t.me/invest_shymkent",
        "user_kz_matrix",
        "Үйден шықпай ақша тап: жарна 7 000 теңге. Kaspi арқылы жеке картаға аудар. Ертең 20 000 теңге ал!",
        90,
    ),

    # ═══════════════════════════════════════════════════════════════
    # CLUSTER C: Translit and Obfuscated Leetspeak
    # ═══════════════════════════════════════════════════════════════
    (
        "msg_translit_01",
        "telegram",
        "tg_growth",
        "Финансовый рост KZ",
        "https://t.me/fin_growth_kz",
        "user_translit_pro",
        "Vlozhi 5000 tg — poluchi 15000 za 2 dnya. Privedi druga i zaberi bonus. Perevod na lichnuyu kartu.",
        110,
    ),
    (
        "msg_translit_02",
        "whatsapp",
        "wa_income",
        "Табыс / Доход",
        "https://chat.whatsapp.com/tabys_income_kz",
        "user_translit_pro",
        "Bugin 20000 tg sal, 3 kun ishinde 50000 al. Tokeuel'siz, 100% kepildik. Kaspi nomerge audar.",
        80,
    ),
    (
        "msg_obfuscated_01",
        "telegram",
        "tg_growth",
        "Финансовый рост KZ",
        "https://t.me/fin_growth_kz",
        "user_stealth_scam",
        "Вл0жи 10000 тг — удв0й баланс за 24 часа! Каспи голд жеке картаға аудар. Шектеулі орын!",
        70,
    ),
    (
        "msg_obfuscated_02",
        "whatsapp",
        "wa_income",
        "Табыс / Доход",
        "https://chat.whatsapp.com/tabys_income_kz",
        "user_stealth_scam",
        "С.р.о.ч.н.о! В.л.0.ж.1 5ООО тг — получи 15ООО тг на Kаspі Gold. Доход гарантирован. Мест мало!",
        50,
    ),

    # ═══════════════════════════════════════════════════════════════
    # CLUSTER D: Matrix, Ponzi & Fake Arbitrage
    # ═══════════════════════════════════════════════════════════════
    (
        "msg_matrix_01",
        "whatsapp",
        "wa_income",
        "Табыс / Доход",
        "https://chat.whatsapp.com/tabys_income_kz",
        "user_matrix_guru",
        "Только до вечера: вступление в закрытый клуб 30 000 ₸. Выплаты идут из взносов новых участников. Приведите троих.",
        150,
    ),
    (
        "msg_matrix_02",
        "telegram",
        "tg_crypto_hub",
        "Крипто Клуб Алматы",
        "https://t.me/crypto_almaty_hub",
        "user_arbitrage_master",
        "Заработок на арбитраже: вход от 30 000 тг. Доход гарантирован 50% в день. Перевод на карту администратора.",
        100,
    ),
    (
        "msg_matrix_03",
        "telegram",
        "tg_growth",
        "Финансовый рост KZ",
        "https://t.me/fin_growth_kz",
        "user_matrix_guru",
        "Матричный проект нового поколения! Вход 5 000 тг, зови друзей, закрой матрицу и получи х10 прибыли!",
        50,
    ),

    # ═══════════════════════════════════════════════════════════════
    # CLUSTER E: Borderline / Suspicious MLM / Unverified Groups
    # ═══════════════════════════════════════════════════════════════
    (
        "msg_med_01",
        "telegram",
        "tg_growth",
        "Финансовый рост KZ",
        "https://t.me/fin_growth_kz",
        "user_partner_hunter",
        "Набираем партнёров в проект. Вход 20 000 ₸, вознаграждение за приглашённых. Подробные условия пока не опубликованы.",
        170,
    ),
    (
        "msg_med_02",
        "whatsapp",
        "wa_income",
        "Табыс / Доход",
        "https://chat.whatsapp.com/tabys_income_kz",
        "user_private_channel",
        "Пассивный доход каждый день. Напиши куратору, чтобы узнать сумму первого взноса. Условия расскажем в личных сообщениях.",
        125,
    ),
    (
        "msg_med_03",
        "telegram",
        "tg_invest",
        "Инвестиции · Шымкент",
        "https://t.me/invest_shymkent",
        "user_invest_speaker",
        "Инвестиционный клуб проводит платную встречу. Обсудим стратегии и риски. Что входит в стоимость, уточняйте у организатора.",
        95,
    ),
    (
        "msg_med_04",
        "telegram",
        "tg_crypto_hub",
        "Крипто Клуб Алматы",
        "https://t.me/crypto_almaty_hub",
        "user_signals_admin",
        "Платный Telegram-канал с сигналами по крипте: стоимость подписки 15 000 тг в месяц. Результаты зависят от рынка.",
        65,
    ),

    # ═══════════════════════════════════════════════════════════════
    # CLUSTER G: Disguised Scams (Fake Jobs, Task Scam, Food Aid Advance Fee)
    # Scammers disguise theft under "work from home", "charity food baskets",
    # or "helping families" while demanding an upfront 5000 KZT deposit/fee.
    # ═══════════════════════════════════════════════════════════════
    (
        "msg_job_01",
        "telegram",
        "tg_growth",
        "Финансовый рост KZ",
        "https://t.me/fin_growth_kz",
        "user_fake_hr",
        "Работа на дому: ставить лайки товарам на Kaspi Магазин. Доход от 25 000 тг в день. Для активации рабочего кабинета внесите залог 5 000 тг куратору.",
        55,
    ),
    (
        "msg_food_01",
        "whatsapp",
        "wa_income",
        "Табыс / Доход",
        "https://chat.whatsapp.com/tabys_income_kz",
        "user_fake_aid",
        "Бесплатная продуктовая помощь семьям: корзина продуктов на 50 000 тг бесплатно! Оплатите только доставку курьером 5 000 тг на личную карту Kaspi.",
        40,
    ),
    (
        "msg_job_kz_01",
        "whatsapp",
        "wa_income",
        "Табыс / Доход",
        "https://chat.whatsapp.com/tabys_income_kz",
        "user_fake_hr_kz",
        "Үйде отырып жұмыс: тауарларға пікір жазу, күніне 30 000 теңге табыс. Жұмысты бастау үшін 5 000 теңге сақтық жарнасын Kaspi-ге аударыңыз.",
        35,
    ),

    # ═══════════════════════════════════════════════════════════════
    # CLUSTER F: Negative Controls (Legitimate education, official warnings)
    # ═══════════════════════════════════════════════════════════════
    (
        "msg_safe_01",
        "telegram",
        "tg_finlit",
        "Финансовая грамотность",
        "https://t.me/finlit_qazaqstan",
        "user_anna_expert",
        "Бесплатная лекция о финансовой грамотности в субботу. Разберём риски и принципы диверсификации. Взносы не нужны.",
        190,
    ),
    (
        "msg_safe_02",
        "whatsapp",
        "wa_community",
        "Қауымдастық KZ",
        "https://chat.whatsapp.com/community_kz_life",
        "user_daulet_teacher",
        "Достар, қаржылық сауаттылық сабағы тегін өтеді. Ешқандай ақша салудың қажеті жоқ. Барлық сұрақты талқылаймыз.",
        175,
    ),
    (
        "msg_safe_03",
        "telegram",
        "tg_finlit",
        "Финансовая грамотность",
        "https://t.me/finlit_qazaqstan",
        "user_broker_halyk",
        "Напоминание: стоимость инвестиций может снижаться. Прошлая доходность не гарантирует будущую. Изучайте документы.",
        145,
    ),
    (
        "msg_safe_04",
        "whatsapp",
        "wa_community",
        "Қауымдастық KZ",
        "https://chat.whatsapp.com/community_kz_life",
        "user_marat_volunteer",
        "Собираемся на волонтёрскую встречу в воскресенье. Участие бесплатное, регистрация открыта для всех.",
        115,
    ),
    (
        "msg_safe_05",
        "telegram",
        "tg_finlit",
        "Финансовая грамотность",
        "https://t.me/finlit_qazaqstan",
        "user_aigerim_reader",
        "Кітап клубының кездесуі ертең сағат 18:00-де. Кіру тегін. Достарыңды шақыр!",
        85,
    ),
    (
        "msg_safe_06",
        "whatsapp",
        "wa_community",
        "Қауымдастық KZ",
        "https://chat.whatsapp.com/community_kz_life",
        "user_budget_consultant",
        "Курс по планированию личного бюджета. Стоимость обучения 8 000 тг. Прибыль и заработок не обещаем.",
        45,
    ),
    (
        "msg_safe_07",
        "telegram",
        "tg_finlit",
        "Финансовая грамотность",
        "https://t.me/finlit_qazaqstan",
        "user_afm_volunteer",
        "Агентство РК по регулированию финрынков предупреждает: не переводите деньги на личные карты Kaspi незнакомым лицам!",
        20,
    ),
]


def seed_database(database_url: Optional[str] = None, clear_existing: bool = True):
    SessionLocal = init_db(database_url)
    session = SessionLocal()

    if clear_existing:
        session.query(EntityRecord).delete()
        session.query(ReviewRecord).delete()
        session.query(AnalysisRecord).delete()
        session.query(MessageRecord).delete()
        session.commit()
        print("Existing messages, analyses, reviews and entities cleared.")

    base_time = datetime.now(timezone.utc)
    inserted = 0

    for msg_id, platform, chat_id, chat_name, chat_url, sender_hash, text, minutes_ago in SCENARIOS:
        pk = make_message_pk(platform, chat_id, msg_id)
        existing = session.get(MessageRecord, pk)
        if not existing:
            rec = MessageRecord(
                id=pk,
                platform=platform,
                chat_id=chat_id,
                chat_name=chat_name,
                chat_url=chat_url,
                message_id=msg_id,
                sender_hash=sender_hash,
                text=text,
                timestamp=base_time - timedelta(minutes=minutes_ago),
                status="PENDING"
            )
            session.add(rec)
            inserted += 1

    session.commit()
    session.close()
    print(f"Database successfully seeded with {inserted} realistic scenario message(s) in status 'PENDING'.")


if __name__ == "__main__":
    seed_database()
