import unittest
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amendments import analyze_amendment


def document(text, **kwargs):
    doc = {"title": "테스트용 문서(실제 법령 아님)", "law_family": "전체", "text": text,
           "publication_status": "현행 법령", "analysis_date": "2026-10-12",
           "source_url": "https://www.law.go.kr/"}
    doc.update(kwargs)
    return doc


def result_for(output, result_id):
    return next(item for item in output["results"] if item["id"].endswith(result_id))


class AmendmentTests(unittest.TestCase):
    def test_multiple_topics_are_reported_instead_of_first_keyword_only(self):
        output = analyze_amendment({"hazardous_chemicals": True, "confined_space": True},
                                   document("HF 취급 관리를 변경한다. 밀폐공간 작업의 기준을 개정한다."))
        self.assertEqual({item["id"].split("-")[-1] for item in output["results"]}, {"chemical", "confined"})
        self.assertTrue(all(item["applicability"] == "관련성 확인" for item in output["results"]))

    def test_unknown_profile_is_not_no_effect(self):
        output = analyze_amendment({}, document("밀폐공간 작업 기준을 변경한다."))
        item = result_for(output, "confined")
        self.assertEqual(item["applicability"], "추가 확인")
        self.assertIn("confined_space", item["missing_fields"])

    def test_explicit_absence_and_unknown_are_different(self):
        item = result_for(analyze_amendment({"confined_space": False}, document("밀폐공간 작업 기준을 개정한다.")), "confined")
        self.assertEqual(item["applicability"], "현재 정보상 비대상")

    def test_comparison_boundary_is_inclusive(self):
        output = analyze_amendment({"headcount": 30}, document("상시근로자 30명 이상 사업장에 안전관리자 기준을 적용한다."))
        item = result_for(output, "workforce")
        self.assertEqual(item["applicability"], "관련성 확인")
        self.assertEqual(item["thresholds"][0]["operator"], ">=")
        self.assertEqual(item["thresholds"][0]["comparison"], "수치 조건 충족")

    def test_strict_boundary_is_not_inclusive(self):
        item = result_for(analyze_amendment({"headcount": 30}, document("상시근로자 30명 초과 사업장의 안전관리자 기준을 변경한다.")), "workforce")
        self.assertEqual(item["applicability"], "현재 정보상 비대상")

    def test_unknown_headcount_does_not_compare_as_zero(self):
        item = result_for(analyze_amendment({}, document("상시근로자 50명 이상 사업장의 안전관리자 기준을 변경한다.")), "workforce")
        self.assertEqual(item["applicability"], "추가 확인")
        self.assertIn("headcount", item["missing_fields"])

    def test_currency_is_converted_to_won(self):
        output = analyze_amendment({"construction_cost_krw": 5000000000, "site_kind": "건설·신축 현장"}, document("공사금액 50억원 이상 건설공사의 기준을 변경한다."))
        item = result_for(output, "construction")
        self.assertEqual(item["thresholds"][0]["value"], 5000000000)
        self.assertEqual(item["applicability"], "관련성 확인")

    def test_area_decimal_and_comma_are_not_sentence_breaks(self):
        item = result_for(analyze_amendment({"gross_floor_area_m2": 3000.5}, document("연면적 3,000.5㎡ 이상 건축물의 기준을 변경한다.")), "building")
        self.assertEqual(item["applicability"], "관련성 확인")
        self.assertEqual(item["thresholds"][0]["value"], 3000.5)
        self.assertIn("3,000.5㎡", item["quote"])

    def test_before_after_uses_explicit_new_threshold(self):
        item = result_for(analyze_amendment({"headcount": 40}, document("상시근로자 기준을 종전 50명 이상에서 30명 이상으로 변경한다.")), "workforce")
        self.assertEqual(item["thresholds"][0]["value"], 30)
        self.assertEqual(item["thresholds"][0]["before"], 50)
        self.assertEqual(item["applicability"], "관련성 확인")

    def test_before_after_without_new_operator_requires_review(self):
        item = result_for(analyze_amendment({"headcount": 40}, document("상시근로자 기준을 50명 이상에서 30명으로 변경한다.")), "workforce")
        self.assertEqual(item["applicability"], "추가 확인")
        self.assertEqual(item["thresholds"], [])

    def test_exception_does_not_become_false_clearance(self):
        item = result_for(analyze_amendment({"headcount": 20}, document("상시근로자 30명 미만은 제외한다. 다만 안전관리자 기준은 별도 적용한다.")), "workforce")
        self.assertEqual(item["applicability"], "추가 확인")

    def test_bill_status_is_not_current_obligation(self):
        output = analyze_amendment({"confined_space": True}, document("밀폐공간 기준을 변경한다.", publication_status="국회 법률안", effective_on="2026-11-01"))
        item = result_for(output, "confined")
        self.assertIn("가결·공포", item["timing"])
        self.assertEqual(output["status"], "추가 검토 필요")

    def test_future_effective_date_is_not_active(self):
        item = result_for(analyze_amendment({"confined_space": True}, document("밀폐공간 기준을 변경한다.", publication_status="공포·시행 예정", effective_on="2026-11-01")), "confined")
        self.assertEqual(item["timing"], "시행 예정: 2026-11-01")

    def test_unknown_publication_status_stays_unknown(self):
        item = result_for(analyze_amendment({"confined_space": True}, document("밀폐공간 기준을 변경한다.", publication_status="상태 미확인", effective_on="2025-01-01")), "confined")
        self.assertIn("상태 미확인", item["timing"])

    def test_dates_are_extracted_without_fabricating_dates(self):
        output = analyze_amendment({"confined_space": True}, document("밀폐공간 기준은 2027년 1월 1일부터 시행한다."))
        self.assertEqual(output["extracted_dates"][0]["date"], "2027-01-01")
        self.assertIn("시행 예정", result_for(output, "confined")["timing"])

    def test_inventory_name_only_never_proves_statutory_classification(self):
        output = analyze_amendment({"chemicals": [{"name": "불산", "concentration_pct": None}]}, document("유해화학물질 기준을 변경한다."))
        item = result_for(output, "chemical")
        self.assertEqual(item["applicability"], "관련성 확인")
        self.assertTrue(any("법적 분류" in e for e in item["profile_evidence"]))
        self.assertFalse(any("법적 대상 확정" in e for e in item["profile_evidence"]))

    def test_no_keywords_is_not_no_effect(self):
        output = analyze_amendment({}, document("제12조의 절차를 일부 변경한다."))
        self.assertEqual(output["status"], "추가 검토 필요")
        self.assertTrue(any("영향 없음의 근거" in warning for warning in output["warnings"]))

    def test_hf_not_found_inside_shift(self):
        output = analyze_amendment({}, document("SHIFT 업무 기준을 변경한다."))
        self.assertEqual(output["results"], [])

    def test_structured_changed_amount_with_unit_conversion(self):
        doc = document("", changes=[{"topic": "공사 규모 변경", "field": "construction_cost_krw", "operator": "이상", "before": 50, "after": 30, "unit": "억원", "source_excerpt": "공사금액 기준을 50억원 이상에서 30억원 이상으로 변경한다.", "effective_on": "2027-01-01"}])
        item = analyze_amendment({"construction_cost_krw": 4000000000}, doc)["results"][0]
        self.assertEqual(item["applicability"], "관련성 확인")
        self.assertEqual(item["thresholds"][0]["value"], 3000000000)
        self.assertEqual(item["thresholds"][0]["before"], 5000000000)
        self.assertEqual(item["timing"], "시행 예정: 2027-01-01")

    def test_structured_missing_unit_is_not_silently_assumed(self):
        doc = document("", changes=[{"field": "gross_floor_area_m2", "operator": ">=", "after": 3000, "source_excerpt": "연면적 기준 변경"}])
        item = analyze_amendment({"gross_floor_area_m2": 5000}, doc)["results"][0]
        self.assertEqual(item["applicability"], "추가 확인")

    def test_structured_source_excerpt_is_required(self):
        doc = document("", changes=[{"field": "headcount", "operator": ">=", "after": 30, "unit": "명"}])
        item = analyze_amendment({"headcount": 40}, doc)["results"][0]
        self.assertEqual(item["applicability"], "추가 확인")

    def test_clauses_do_not_share_unrelated_thresholds(self):
        doc = document("상시근로자 50명 이상 사업장의 안전관리자 기준을 변경한다.\n밀폐공간 구조 기준을 변경한다.")
        output = analyze_amendment({"headcount": 10, "confined_space": True}, doc)
        self.assertEqual(result_for(output, "workforce")["applicability"], "현재 정보상 비대상")
        self.assertEqual(result_for(output, "confined")["applicability"], "관련성 확인")
        self.assertEqual(result_for(output, "confined")["thresholds"], [])

    def test_unqualified_area_does_not_use_gross_floor_area(self):
        item = result_for(analyze_amendment({"gross_floor_area_m2": 5000}, document("바닥면적 3000㎡ 이상 건축물의 기준을 변경한다.")), "building")
        self.assertEqual(item["applicability"], "추가 확인")
        self.assertEqual(item["thresholds"], [])

    def test_multiple_missing_conditions_do_not_become_nontarget(self):
        doc = document("상시근로자 30명 이상 및 공사금액 50억원 이상 건설공사의 기준을 변경한다.")
        item = result_for(analyze_amendment({"headcount": 10, "site_kind": "건설·신축 현장"}, doc), "construction")
        self.assertEqual(item["applicability"], "추가 확인")
        self.assertIn("construction_cost_krw", item["missing_fields"])

    def test_unrelated_and_word_does_not_join_numeric_conditions(self):
        doc = document("상시근로자 30명 이상, 공사금액 50억원 이상 건설공사의 안전 및 보건 절차를 변경한다.")
        output = analyze_amendment({"headcount": 40, "construction_cost_krw": 1000000000, "site_kind": "건설·신축 현장"}, doc)
        item = result_for(output, "workforce")
        self.assertEqual(item["applicability"], "추가 확인")
        self.assertEqual({t["comparison"] for t in item["thresholds"]}, {"수치 조건 충족", "수치 조건 미충족"})

    def test_mixed_conditions_require_review_even_with_and_or_words(self):
        for connective in ("및", "또는", "및 또는", "이고", ","):
            with self.subTest(connective=connective):
                doc = document(f"상시근로자 30명 이상 {connective} 공사금액 50억원 이상 건설공사 기준을 변경한다.")
                output = analyze_amendment({"headcount": 40, "construction_cost_krw": 1000000000, "site_kind": "건설·신축 현장"}, doc)
                self.assertEqual(result_for(output, "workforce")["applicability"], "추가 확인")

    def test_multiple_failed_numbers_do_not_claim_combined_exemption(self):
        doc = document("상시근로자 30명 이상 또는 공사금액 50억원 이상 건설공사 기준을 변경한다.")
        output = analyze_amendment({"headcount": 10, "construction_cost_krw": 1000000000, "site_kind": "건설·신축 현장"}, doc)
        self.assertEqual(result_for(output, "workforce")["applicability"], "추가 확인")

    def test_structured_nonfinite_and_invalid_values_are_not_thresholds(self):
        for value in (float("nan"), float("inf"), -10, "NaN", "1e309", "잘못된 수치", True):
            with self.subTest(value=value):
                doc = document("", changes=[{"field": "headcount", "operator": ">=", "after": value, "unit": "명", "source_excerpt": "상시근로자 기준 변경"}])
                item = analyze_amendment({"headcount": 40}, doc)["results"][0]
                self.assertEqual(item["applicability"], "추가 확인")
                self.assertEqual(item["thresholds"], [])

    def test_overflow_during_currency_conversion_is_invalid(self):
        doc = document("", changes=[{"field": "construction_cost_krw", "operator": ">=", "after": "1e308", "unit": "조원", "source_excerpt": "공사금액 기준 변경"}])
        item = analyze_amendment({"construction_cost_krw": 1000000000}, doc)["results"][0]
        self.assertEqual(item["applicability"], "추가 확인")
        self.assertEqual(item["thresholds"], [])

    def test_future_publication_conflicts_with_current_law_status(self):
        doc = document("밀폐공간 기준을 변경한다.", published_on="2027-01-01", effective_on="2027-02-01")
        output = analyze_amendment({"confined_space": True}, doc)
        self.assertEqual(output["status"], "추가 검토 필요")
        self.assertIn("입력 충돌", result_for(output, "confined")["timing"])
        self.assertTrue(any("미래" in warning for warning in output["warnings"]))

    def test_effective_before_publication_requires_source_review(self):
        doc = document("밀폐공간 기준을 변경한다.", published_on="2026-10-01", effective_on="2026-09-01")
        output = analyze_amendment({"confined_space": True}, doc)
        self.assertEqual(output["status"], "추가 검토 필요")
        self.assertIn("순서 확인 필요", result_for(output, "confined")["timing"])

    def test_long_numeric_paste_is_bounded_and_not_a_tail_threshold(self):
        start = time.monotonic()
        doc = document("상시근로자 " + "1" * 200000 + "명 이상 사업장의 안전관리자 기준을 변경한다.")
        output = analyze_amendment({"headcount": 40}, doc)
        self.assertLess(time.monotonic() - start, 3.0)
        item = result_for(output, "workforce")
        self.assertEqual(item["thresholds"], [])
        self.assertEqual(item["applicability"], "추가 확인")


if __name__ == "__main__":
    unittest.main()
