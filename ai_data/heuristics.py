import re
from typing import List, Tuple, Dict, Any
from .models import ReasonCodeEnum, ReasonItem, RiskLevelEnum, AnalysisResult, compute_calibrated_confidence
from .normalizer import find_exact_substring, detect_language


# Multilingual Rule Patterns: (Pattern Regex, Reason Code, Base Weight)
RULES = [
    # 1. UNREALISTIC_RETURN (Обещание сверхдоходности / быстрого удвоения)
    (
        r"(?:получи[ть]?|забери|ал|тап)\s+\d+[\s\d]*\s*(?:тг|₸|теңге|тенге|руб|долл|\$)?\s*(?:уже\s*)?(?:завтра|ертең|бүгін|сегодня|за\s+\d+\s*(?:дня|күн|сағат))",
        ReasonCodeEnum.UNREALISTIC_RETURN.value,
        35
    ),
    (
        r"(?:ертең|завтра|бүгін|сегодня|за\s+\d+\s*(?:дня|күн|сағат|dnya|chasa))\s+\d+[\s\d]*\s*(?:тг|₸|теңге|тенге|руб|долл|\$)?\s*(?:ал|тап|получи[ть]?|забери)",
        ReasonCodeEnum.UNREALISTIC_RETURN.value,
        35
    ),
    (
        r"(?:доход|прибыль|табыс|пассивный\s*доход|пассивті\s*табыс)\s+(?:гарантирован\s+)?(?:от\s*)?\d+%\s*(?:в|за|ішінде)?\s*(?:день|неделю|месяц|тәулік|ай)",
        ReasonCodeEnum.UNREALISTIC_RETURN.value,
        35
    ),
    (
        r"(?:х\d+|[1-9]00%|[1-9]\d{2,}%)\s*(?:прибыли|дохода|көбейт|өсім|за\s+неделю|в\s+неделю)?",
        ReasonCodeEnum.UNREALISTIC_RETURN.value,
        35
    ),
    (
        r"(?:екі\s*есе|в\s*два\s*раза|удв[о0]й|удвоить|көбейт|2\s*есе)\s*(?:ақша[ңд]?|депозит|вложения|капитал|доход|баланс)?",
        ReasonCodeEnum.UNREALISTIC_RETURN.value,
        35
    ),
    (
        r"(?:poluchi|zaberi)\s+\d+[\s\d]*\s*(?:tg)?\s*(?:za|v)\s+\d+\s*(?:dnya|chasa|dney)",
        ReasonCodeEnum.UNREALISTIC_RETURN.value,
        35
    ),
    (
        r"(?:\d+\s*(?:kun|kүн)\s*ishinde|\d+\s*(?:дня|дней)\s*в)\s+\d+[\s\d]*\s*(?:al|ал)",
        ReasonCodeEnum.UNREALISTIC_RETURN.value,
        35
    ),
    (
        r"(?:poluchi|zaberi|получи[ть]?|забери|ал)\s+\d+[\s\d]*\s*(?:тг|₸|теңге|тенге|tg)?\s*(?:сразу|srazu|уже\s*сейчас|sraz|(?:за|в)\s+\d*\s*(?:дн[яей]+|час[аов]*|недел[юи]|күн|апта))",
        ReasonCodeEnum.UNREALISTIC_RETURN.value,
        35
    ),
    (
        r"(?:заработок\s+от\s+\d+[\s\d]*\s*(?:тг|теңге|тенге)|айына\s+\d+[\s\d]*\s*теңге\s+табуға\s+болады)",
        ReasonCodeEnum.UNREALISTIC_RETURN.value,
        25
    ),

    # 2. GUARANTEED_PROFIT (Гарантия дохода / отсутствие рисков)
    (
        r"(?:доход\s+гарантирован|табысқа\s+кепілдік\s+береміз|кепілдік\s+береміз|100%\s*гаранти[яи]|гарантия\s+прибыли|гарантированный\s+доход|100%\s*kepildik)",
        ReasonCodeEnum.GUARANTEED_PROFIT.value,
        25
    ),
    (
        r"(?:без\s+риска|рисков\s+нет|тәуекелсіз|толық\s+сенімді|tokeuel['`]?siz|tolyq\s+senimdi)",
        ReasonCodeEnum.GUARANTEED_PROFIT.value,
        25
    ),

    # 3. MONEY_REQUEST (Требование денег / взноса / депозита)
    (
        r"(?:вл[о0]жи|вложить|вклад|сал|кіру\s+жарнасы|вход|входной\s+билет|старт\s+от|vlozhi|kiru\s+zharnasy|депозит|жарна)\s+(?:от\s*)?\d+[\s\d]*\s*(?:₸|тг|теңге|тенге|\$)?",
        ReasonCodeEnum.MONEY_REQUEST.value,
        25
    ),
    (
        r"\d+[\s\d]*\s*(?:₸|тг|теңге|тенге)\s+(?:сал|жарна)",
        ReasonCodeEnum.MONEY_REQUEST.value,
        25
    ),
    (
        r"\b\d+[\s\d]*\s*sal\b",
        ReasonCodeEnum.MONEY_REQUEST.value,
        25
    ),
    (
        r"(?:сумму\s+первого\s+взноса|жарна\s+қажет|первый\s+взнос|вступительный\s+взнос|вступление\s+в\s+закрытый\s+клуб\s+\d+|платную\s+встречу|платный\s+telegram-канал|стоимость\s+подписки|доступ\s+\d+[\s\d]*\s*(?:₸|тг))",
        ReasonCodeEnum.MONEY_REQUEST.value,
        25
    ),
    (
        r"(?:стоимость\s+курса\s+\d+[\s\d]*\s*(?:тг|теңге|тенге)?|под\s+залог\s+(?:авто|недвижимости)|несие\s+беру\s+мүмкіндігі|процентная\s+ставка\s+от\s+\d+%)",
        ReasonCodeEnum.MONEY_REQUEST.value,
        20
    ),
    (
        r"(?:личкаға\s+жазыңыз|толығырақ\s+жекеде|қалғанын\s+лс-та|пишите\s+в\s+whatsapp|ватсапқа\s+жазыңыз|делимся\s+сигналами|трейдинг\s+бойынша\s+жеке\s+кеңес[а-я]*|арбитраж\s+жасауды\s+үйретемін)",
        ReasonCodeEnum.MONEY_REQUEST.value,
        20
    ),

    # 4. REFERRAL (Привлечение людей / реферальная сеть)
    (
        r"(?:пригласи|приведи|досыңды\s+шақыр|шақырсаң|privedi|dostaryndy\s+shaqyr|шақырған\s+үшін|зови\s+друзей|приведите|достарыңа\s+айт)\s*(?:\d+|екі|троих|дос|друг[а-я]*|адам|человек[а-я]*)?",
        ReasonCodeEnum.REFERRAL.value,
        25
    ),
    (
        r"(?:за\s+каждого\s*(?:нового)?\s*участника|бонус\s+за\s+(?:регистрацию|приглашённых|друзей)|сыйақы\s+аласың|вознаграждение\s+за\s+приглашённых|выплаты\s+идут\s+из\s+взносов|серіктестік\s+бағдарлама|партнерк[ае]|реферал[а-я]*)",
        ReasonCodeEnum.REFERRAL.value,
        25
    ),
    (
        r"(?:партнерск(?:ая|ой|ую|ие)\s+программ[а-я]*|строй\s+свою\s+команду(?:\s+консультантов)?|команд[а-я]+\s+құру|желілік\s+компания|өз\s+командаңды\s+жинап|торгов(?:ой|ая)\s+команд[а-я]*)",
        ReasonCodeEnum.REFERRAL.value,
        25
    ),

    # 5. URGENCY (Искусственная срочность / давление)
    (
        r"(?:осталось\s+\d+\s+мест[ао]?|только\s+до\s+вечера|только\s+сегодня|шектеулі\s+орын|соңғы\s+\d+\s+орын|успей\s+зайти|места\s+ограничены|срочный\s+сбор)",
        ReasonCodeEnum.URGENCY.value,
        20
    ),

    # 6. PERSONAL_TRANSFER (Перевод на личные реквизиты)
    (
        r"(?:на\s+личную\s+карту|жеке\s+картаға|kaspi\s+арқылы\s+жеке\s+картаға\s+аудар|картаға\s+аудар|perevod\s+na\s+lichnuyu\s+kartu|перевод\s+на\s+карту|kaspi\s+голд\s+жеке|kaspi\s+nomerge\s+audar|номерге\s+аудар)",
        ReasonCodeEnum.PERSONAL_TRANSFER.value,
        25
    ),
]

# Educational or negative safety patterns that indicate legitimate/educational context
DISCLAIMERS = [
    r"взносы\s+не\s+нужны",
    r"ақша\s+салудың\s+қажеті\s+жоқ",
    r"кіру\s+тегін",
    r"участие\s+бесплатное",
    r"бесплатная\s+лекция",
    r"тегін\s+өтеді",
    r"қатысу\s+тегін",
    r"не\s+гарантирует",
    r"прибыль\s+.*не\s+обещаем",
    r"презентацию\s+о\s+распознавании\s+финансовых\s+пирамид",
    r"финансовая\s+грамотность",
    r"доход\s+не\s+гарантирован",
    r"ешқашан\s+құпия\s+код",
    r"скидк[а-я]*\s+на\s+(?:следующую\s+)?поездку",
    r"жеңілдік\s+ал",
    r"yandex\s+go",
    r"киім\s+дүкен",
    r"kaspi\s+red",
]


def analyze_with_heuristics(text: str) -> AnalysisResult:
    """
    Analyzes message using deterministic multilingual heuristics and exact evidence slicing.
    Guarantees that every evidence string is an exact substring of the original text.
    """
    lang = detect_language(text)
    reasons_dict: Dict[str, str] = {}
    matched_weights: List[int] = []

    # Check for disclaimers / benign context
    has_disclaimer = any(re.search(pat, text, re.IGNORECASE) for pat in DISCLAIMERS)

    for pattern, code, weight in RULES:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Sliced directly from the original text!
            start, end = match.span()
            evidence = text[start:end].strip()
            
            # Avoid duplicate reasons, keep best evidence
            if code not in reasons_dict:
                reasons_dict[code] = evidence
                matched_weights.append(weight)

    has_unrealistic = ReasonCodeEnum.UNREALISTIC_RETURN.value in reasons_dict
    has_money = ReasonCodeEnum.MONEY_REQUEST.value in reasons_dict
    has_referral = ReasonCodeEnum.REFERRAL.value in reasons_dict
    has_guarantee = ReasonCodeEnum.GUARANTEED_PROFIT.value in reasons_dict
    has_urgency = ReasonCodeEnum.URGENCY.value in reasons_dict
    has_transfer = ReasonCodeEnum.PERSONAL_TRANSFER.value in reasons_dict

    total_score = 0
    if reasons_dict:
        # Base accumulation
        total_score = sum(matched_weights)
        
        # Synergy boost for classical pyramid triads:
        # If there is unrealistic return + any other factor -> strong boost
        if has_unrealistic:
            if has_money or has_transfer or has_referral or has_guarantee:
                total_score = max(total_score + 15, 75)
            else:
                total_score = max(total_score, 65)
        
        # Transfer to personal card + money request / guarantee -> strong pyramid sign
        if has_transfer and (has_money or has_guarantee or has_urgency):
            total_score = max(total_score + 15, 75)

        # Money request + referral + urgency/guarantee -> high risk
        if has_money and has_referral and (has_urgency or has_guarantee):
            total_score = max(total_score + 15, 75)

        # If it ONLY has money request and referral without promises of super-returns or urgency
        # (e.g. standard affiliate / partner onboarding), keep at MEDIUM risk (30-55)
        if set(reasons_dict.keys()) == {ReasonCodeEnum.MONEY_REQUEST.value, ReasonCodeEnum.REFERRAL.value} and not has_unrealistic and not has_transfer:
            total_score = 55
        elif len(reasons_dict) == 1 and not has_unrealistic:
            # Single moderate signal (e.g. paid webinar, paid meeting, simple affiliate) -> MEDIUM
            total_score = min(total_score, 48)

        total_score = min(98, max(30, total_score))
    else:
        # No suspicious patterns detected
        if re.search(r"\b(?:инвестиц|пассивный|табыс|қаржы|крипт|доход)\b", text, re.IGNORECASE):
            total_score = 15
        else:
            total_score = 2

    # Contextual check for benign consumer promotions and courses
    is_consumer_promo = bool(re.search(r"\b(?:yandex\s*go|такси|киім\s+дүкен|поездк[а-я]|скидк[а-я]*\s+на|жеңілдік|kaspi\s*red)\b", text, re.IGNORECASE))
    is_course = bool(re.search(r"\b(?:обучени[ея]|курс[а-я]*|мамандық|оқу\s+мерзімі|выпускник[а-я]*)\b", text, re.IGNORECASE))

    is_critical_pyramid = (
        (has_unrealistic and (has_money or has_transfer or has_referral or has_guarantee))
        or (has_transfer and (has_money or has_guarantee))
    )

    if is_consumer_promo and not is_critical_pyramid and not has_transfer:
        total_score = min(total_score, 10)
        reasons_dict.clear()
    elif is_course and total_score >= 60 and not has_transfer:
        total_score = 45
    elif has_disclaimer:
        if is_critical_pyramid:
            # Disclaimer on overt pyramid: cannot sanitize scam, preserve HIGH
            total_score = max(total_score, 75)
        elif reasons_dict:
            # Ambiguous grey-zone with disclaimer: moderate to MEDIUM, preserve evidence
            total_score = min(45, max(35, total_score))
        else:
            # Genuine benign / educational
            total_score = min(total_score, 12)
            reasons_dict.clear()

    # Determine risk level strictly according to MVP Plan:
    # LOW: 0-29, MEDIUM: 30-59, HIGH: 60-100
    if total_score >= 60:
        level = RiskLevelEnum.HIGH
    elif total_score >= 30:
        level = RiskLevelEnum.MEDIUM
    else:
        level = RiskLevelEnum.LOW

    # Format reasons
    reasons_list = [
        ReasonItem(code=code, evidence=ev)
        for code, ev in reasons_dict.items()
    ]

    # Generate contextual explanation
    explanation = _generate_explanation(reasons_list, level, lang)
    # Calibrated confidence reflects signal clarity and context sufficiency (bounded [0.0, 0.95])
    confidence = compute_calibrated_confidence(
        risk_level=level,
        reasons_count=len(reasons_list),
        text=text,
    )

    return AnalysisResult(
        risk_score=total_score,
        risk_level=level,
        reasons=reasons_list,
        explanation=explanation,
        confidence=confidence,
        model_version="safenet-heuristics-v1.0"
    )


def _generate_explanation(reasons: List[ReasonItem], level: RiskLevelEnum, lang: str) -> str:
    if level == RiskLevelEnum.HIGH:
        if lang == "kz":
            return "Қаржылық пирамида сұлбаларына тән өзара байланысты белгілер тіркелді: жоғары табыс уәдесі, жарна салу талабы немесе адам шақыру жүйесі. Аналитикалық тексеру қажет."
        return "Зафиксировано несколько взаимосвязанных признаков, характерных для схем финансовых пирамид: обещание сверхдоходности, привлечение рефералов или требование перевода средств. Требуется аналитическая проверка."
    
    elif level == RiskLevelEnum.MEDIUM:
        if lang == "kz":
            return "Күдікті немесе жанама тәуекел белгілері анықталды (жарна, серіктестік төлемдері). Толық шарттары көрсетілмеген, мониторинг ұсынылады."
        return "Выявлены неоднозначные или косвенные признаки риска (запрос взносов или партнерские выплаты). Условия проекта непрозрачны, рекомендуется мониторинг."
    
    else:
        if lang == "kz":
            return "Ұсынылған деректерде белгілі қаржылық тәуекел белгілері анықталмады. Хабарлама бейтарап немесе білім беру сипатына ие (төмен тәуекел толық қауіпсіздік кепілі болып табылмайды)."
        return "В предоставленных данных известные признаки финансовых рисков не обнаружены. Сообщение носит нейтральный или образовательный характер (низкий риск не является гарантией абсолютной безопасности)."
