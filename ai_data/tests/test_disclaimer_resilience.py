import unittest
from ai_data.models import RiskLevelEnum, AnalysisResult, ReasonItem
from ai_data.heuristics import analyze_with_heuristics
from ai_data.analyzer import synthesize_risk


class TestDisclaimerAndAmbiguousRiskResilience(unittest.TestCase):
    """
    Regression tests verifying that:
    1. Overt pyramid schemes with fake/legal disclaimers cannot bypass HIGH risk classification.
    2. Ambiguous grey-zone patterns with disclaimers remain in MEDIUM (not suppressed to LOW).
    3. Benign educational / institutional / consumer messages remain in LOW.
    """

    def test_overt_pyramid_with_fake_disclaimer_remains_high(self):
        text = "Вложи 10 000 тг и получи 500 000 за неделю! Перевод на личную карту Kaspi. Доход не гарантирован, риски есть."
        heur = analyze_with_heuristics(text)
        self.assertEqual(heur.risk_level, RiskLevelEnum.HIGH)
        self.assertGreaterEqual(heur.risk_score, 75)
        codes = {r.code for r in heur.reasons}
        self.assertIn("UNREALISTIC_RETURN", codes)
        self.assertIn("PERSONAL_TRANSFER", codes)

        # In hybrid synthesis with mock Gemini
        gem = AnalysisResult(
            risk_score=85,
            risk_level=RiskLevelEnum.HIGH,
            reasons=[ReasonItem(code="UNREALISTIC_RETURN", evidence="получи 500 000 за неделю")],
            explanation="Пирамида",
            confidence=0.95
        )
        synth = synthesize_risk(text, gem, heur, lang="ru", is_obfuscated=False, target_model="gemini-3.5-flash-lite")
        self.assertEqual(synth.risk_level, RiskLevelEnum.HIGH)
        self.assertGreaterEqual(synth.risk_score, 75)
        self.assertTrue(len(synth.reasons) >= 1)

    def test_ambiguous_forex_signals_with_disclaimer_is_medium(self):
        text = "Присоединяйтесь к нашей торговой команде на Forex. Делимся сигналами, но помните о рисках: торговля на финансовых рынках сопряжена с риском потери капитала."
        heur = analyze_with_heuristics(text)
        gem = AnalysisResult(
            risk_score=15,
            risk_level=RiskLevelEnum.LOW,
            reasons=[],
            explanation="",
            confidence=0.9
        )
        synth = synthesize_risk(text, gem, heur, lang="ru", is_obfuscated=False, target_model="gemini-3.5-flash-lite")
        self.assertEqual(synth.risk_level, RiskLevelEnum.MEDIUM)
        self.assertGreaterEqual(synth.risk_score, 30)
        self.assertLessEqual(synth.risk_score, 59)
        self.assertTrue(any("торговой команде" in r.evidence or "сигналами" in r.evidence for r in synth.reasons))

    def test_ambiguous_crypto_consulting_kz_with_disclaimer_is_medium(self):
        text = "Криптовалюта нарығындағы трейдинг бойынша жеке кеңестер. Тәуекелдер бар, бірақ нарықты дұрыс талдау арқылы жақсы нәтижеге жетуге болады. Толығырақ жекеде."
        heur = analyze_with_heuristics(text)
        gem = AnalysisResult(
            risk_score=15,
            risk_level=RiskLevelEnum.LOW,
            reasons=[],
            explanation="",
            confidence=0.9
        )
        synth = synthesize_risk(text, gem, heur, lang="kz", is_obfuscated=False, target_model="gemini-3.5-flash-lite")
        self.assertEqual(synth.risk_level, RiskLevelEnum.MEDIUM)
        self.assertGreaterEqual(synth.risk_score, 30)
        self.assertLessEqual(synth.risk_score, 59)

    def test_benign_financial_literacy_with_disclaimer_remains_low(self):
        text = "Бесплатная лекция по инвестициям и финансовой грамотности. Взносы не нужны, прибыль не гарантируем."
        heur = analyze_with_heuristics(text)
        self.assertEqual(heur.risk_level, RiskLevelEnum.LOW)
        self.assertLessEqual(heur.risk_score, 20)
        self.assertEqual(len(heur.reasons), 0)

        gem = AnalysisResult(
            risk_score=0,
            risk_level=RiskLevelEnum.LOW,
            reasons=[],
            explanation="",
            confidence=0.95
        )
        synth = synthesize_risk(text, gem, heur, lang="ru", is_obfuscated=False, target_model="gemini-3.5-flash-lite")
        self.assertEqual(synth.risk_level, RiskLevelEnum.LOW)
        self.assertLessEqual(synth.risk_score, 20)
        self.assertEqual(len(synth.reasons), 0)

    def test_consumer_promo_discount_remains_low(self):
        text = "Пригласи друга в Yandex Go и получи скидку 500 тг на следующую поездку при заказе такси."
        heur = analyze_with_heuristics(text)
        gem = AnalysisResult(
            risk_score=0,
            risk_level=RiskLevelEnum.LOW,
            reasons=[],
            explanation="",
            confidence=0.95
        )
        synth = synthesize_risk(text, gem, heur, lang="ru", is_obfuscated=False, target_model="gemini-3.5-flash-lite")
        self.assertEqual(synth.risk_level, RiskLevelEnum.LOW)
        self.assertLessEqual(synth.risk_score, 20)
        self.assertEqual(len(synth.reasons), 0)


if __name__ == "__main__":
    unittest.main()
