"""Source-based amendment relevance screening, without a model or legal verdict.

The input text remains the authority. Numeric comparisons are only performed
for a recognised measurement with an explicit unit and comparison operator.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    family: str
    terms: tuple[str, ...]
    fields: tuple[str, ...] = ()
    processes: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()


TOPICS = (
    Topic("confined", "밀폐공간 작업", "산업안전보건", ("밀폐공간", "산소결핍", "질식"), ("confined_space",), actions=("해당 장소의 밀폐공간 분류와 작업 절차·교육·구조 준비에 관한 변경 내용을 확인하세요.",)),
    Topic("height", "고소·추락 위험 작업", "산업안전보건", ("고소작업", "고소 작업", "추락", "비계", "안전난간"), ("work_at_height",), ("construction",), ("고소 작업 장소와 작업 방법을 대조하고 변경된 보호 조치의 적용 범위를 확인하세요.",)),
    Topic("excavation", "굴착 작업", "건설", ("굴착", "흙막이", "토사붕괴"), ("excavation",), actions=("굴착 깊이·지반·흙막이 등 조항에 필요한 별도 제원을 확인하세요.",)),
    Topic("lifting", "양중·중량물 작업", "산업안전보건", ("양중", "크레인", "중량물", "인양", "지게차"), ("lifting_work",), ("logistics",), ("해당 장비의 종류·용량·작업 방법 및 검사·작업계획 관련 변경을 대조하세요.",)),
    Topic("hotwork", "화기 작업", "산업안전보건", ("화기작업", "화기 작업", "용접", "용단"), ("hot_work",), ("welding",), ("화기 작업 장소와 가연물·가스 존재 여부를 대조하고 변경된 조치를 확인하세요.",)),
    Topic("explosive", "인화·폭발 위험", "산업안전보건", ("폭발위험", "폭발 위험", "방폭", "인화성", "가연성 가스"), ("flammable_atmosphere",), ("painting", "wet_chemical", "battery"), ("물질 특성·취급 방식·위험장소 분류를 확인하고 조항의 정확한 적용 조건을 대조하세요.",)),
    Topic("msds", "물질안전보건자료", "산업안전보건", ("물질안전보건자료", "MSDS", "SDS"), ("msds_target",), actions=("대상 제품별 최신 MSDS, 제출·제공·게시·교육 중 실제 변경 항목을 확인하세요.",)),
    Topic("chemical", "화학물질 취급", "화학물질", ("화학물질", "유해화학", "화학약품", "불산", "불화수소", "염산", "황산", "HF"), ("hazardous_chemicals",), ("wet_chemical", "painting", "battery"), ("물질의 CAS·농도·사용량·최대 저장량과 공식 분류·별표를 원문 기준으로 확인하세요.",)),
    Topic("psm", "공정안전보고서", "산업안전보건", ("공정안전보고서", "공정안전관리", "PSM"), ("psm_confirmed",), actions=("사업장 업종과 대상 물질·규정량 및 기존 PSM 대상 여부를 별표와 대조하세요.",)),
    Topic("medical", "특수건강진단", "산업안전보건", ("특수건강진단", "특수 건강진단"), ("special_health_exam_target",), actions=("작업자의 실제 노출 유해인자와 검진 주기·대상 변경 내용을 확인하세요.",)),
    Topic("measurement", "작업환경측정", "산업안전보건", ("작업환경측정", "작업환경 측정"), ("work_environment_measurement_target",), actions=("유해인자·노출 작업·측정 주기 및 예외 조건을 원문과 대조하세요.",)),
    Topic("machine", "위험 기계·설비", "산업안전보건", ("프레스", "전단기", "위험기계", "위험 기계", "안전검사", "산업용 로봇", "컨베이어"), ("dangerous_machines",), ("press", "machining", "assembly", "logistics"), ("보유 장비의 종류·규격·용량과 별표상 검사·인증 대상 조건을 대조하세요.",)),
    Topic("contractor", "도급·협력업체 작업", "산업안전보건", ("도급", "수급인", "협력업체", "협력사", "관계수급인"), ("contractor_work",), actions=("도급인·수급인의 역할과 실제 작업 장소를 구분하고 변경된 의무의 주체를 확인하세요.",)),
    Topic("workforce", "안전보건 조직·인원 기준", "산업안전보건", ("상시근로자", "상시 근로자", "안전관리자", "보건관리자", "안전보건관리책임자", "안전보건관리담당자", "산업안전보건위원회"), actions=("업종·상시근로자 산정 기준·선임 형태 및 별표의 적용 조건을 확인하세요.",)),
    Topic("risk", "위험성평가·작업 안전", "산업안전보건", ("위험성평가", "위험성 평가", "작업안전분석", "JSA", "산업안전보건", "중대재해"), actions=("변경 조항의 주체·대상 작업·시행일을 확인하고 현재 절차와 차이를 기록하세요.",)),
    Topic("fire", "소방·피난·방화", "소방", ("소방시설", "소방안전관리", "소화설비", "소화기", "피난", "방화", "화재"), actions=("건축물 용도·면적·층수·특정소방대상물 분류와 해당 별표를 원문 기준으로 확인하세요.",)),
    Topic("dangerousgoods", "위험물 시설·취급", "위험물", ("위험물", "지정수량", "제조소", "저장소", "취급소"), ("dangerous_goods_facility",), actions=("물질의 공식 위험물 분류·지정수량 배수·허가 시설 구분과 변경 내용을 대조하세요.",)),
    Topic("gas", "가스 시설", "가스", ("고압가스", "압축가스", "액화가스", "가스설비", "가스 시설"), ("compressed_gas",), ("utility",), ("가스 종류·압력·용량·시설 허가 구분을 확인하고 해당 기술기준의 변경 내용을 대조하세요.",)),
    Topic("building", "건축물·인허가", "건축", ("건축물", "건축법", "연면적", "건축면적", "바닥면적", "층수", "지상층", "지하층", "용도변경", "건축허가"), actions=("건축물 용도·구조·규모와 허가 시점·경과조치·별표의 적용 범위를 확인하세요.",)),
    Topic("construction", "건설·신축 현장", "건설", ("건설공사", "공사금액", "공사 금액", "건설현장", "신축", "대수선", "건설업"), ("construction_project", "new_building"), ("construction",), ("발주자·시공자·도급인의 역할, 공사종류·금액·착공일과 경과조치를 대조하세요.",)),
    Topic("wastewater", "폐수 배출", "환경", ("폐수", "수질", "폐수배출시설"), ("wastewater_discharge",), actions=("시설 분류·배출량·오염물질·허가 조건과 개정된 기준을 대조하세요.",)),
    Topic("air", "대기 배출", "환경", ("대기오염", "대기배출", "대기 배출", "대기환경", "배출가스"), ("air_emission_facility",), actions=("시설 분류·규모·오염물질과 허가 조건 및 배출 기준의 변경을 확인하세요.",)),
    Topic("waste", "폐기물", "환경", ("폐기물", "지정폐기물"), ("designated_waste",), actions=("폐기물 종류·발생량·보관·운반·처리 방식과 개정된 관리 기준을 대조하세요.",)),
    Topic("asbestos", "석면 작업", "산업안전보건", ("석면",), ("asbestos_work",), actions=("석면 조사·해체·제거 작업의 범위와 발주자·수행자의 역할을 대조하세요.",)),
)

FIELD_LABELS = {
    "headcount": "상시근로자 수", "contractor_workers": "협력업체 근로자 수",
    "construction_cost_krw": "공사금액", "building_area_m2": "건축면적",
    "gross_floor_area_m2": "연면적", "ground_floors": "지상 층수",
    "basement_floors": "지하 층수", "height_m": "건축물 높이",
    "confined_space": "밀폐공간 작업", "work_at_height": "고소 작업",
    "excavation": "굴착 작업", "lifting_work": "양중 작업", "hot_work": "화기 작업",
    "flammable_atmosphere": "인화·폭발 위험장소", "hazardous_chemicals": "유해화학물질 취급",
    "msds_target": "MSDS 대상 제품", "special_health_exam_target": "특수건강진단 대상",
    "work_environment_measurement_target": "작업환경측정 대상", "psm_confirmed": "PSM 대상 확인",
    "dangerous_goods_facility": "위험물 시설", "dangerous_machines": "위험 기계·설비",
    "construction_project": "건설공사", "new_building": "신축 건축물",
    "compressed_gas": "압축·고압가스", "contractor_work": "도급 작업",
    "wastewater_discharge": "폐수 배출", "air_emission_facility": "대기 배출시설",
    "designated_waste": "지정폐기물", "asbestos_work": "석면 작업",
}
BOOL_FIELDS = {f for t in TOPICS for f in t.fields}
# Bound numeric tokens and anchor their edges. Without these bounds a long
# digit-only paste can make a suffix-dependent finditer rescan every tail.
NUMBER = r"(?<![\d,.\-])(?:\d[\d,]{0,24}(?:\.\d{1,10})?(?:\s*[만천백])?)(?![\d,.])"
COMPARATORS = {"이상": ">=", "초과": ">", "이하": "<=", "미만": "<", "같다": "==", ">=": ">=", ">": ">", "<=": "<=", "<": "<", "==": "==", "=": "=="}
OP_PATTERN = r"(?:이상|초과|이하|미만|>=|<=|==|>|<|=)"
BASE_UNITS = {"headcount": "명", "contractor_workers": "명", "construction_cost_krw": "원", "building_area_m2": "㎡", "gross_floor_area_m2": "㎡", "ground_floors": "층", "basement_floors": "층", "height_m": "m"}
PROCESS_LABELS = {"cleanroom": "클린룸", "wet_chemical": "습식·화학처리", "press": "프레스·전단", "machining": "절삭·기계가공", "assembly": "조립", "welding": "용접·용단", "painting": "도장", "heat_treatment": "열처리", "food": "식품 제조", "logistics": "물류·창고", "utility": "유틸리티", "battery": "배터리 제조", "construction": "건설·신축"}
COMMON_ACTION = "공식 원문의 조항·별표·단서·경과조치를 검토한 뒤 적용 여부와 담당자·완료일을 기록하세요."


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        s = str(value).replace(",", "").replace(" ", "")
        factor = {"만": 10000, "천": 1000, "백": 100}.get(s[-1:], 1)
        if factor != 1:
            s = s[:-1]
        n = float(s) * factor
        return n if n >= 0 and math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def _normalise_numeric(field: str, value: Any, unit: str) -> float | None:
    n = _number(value)
    if n is None:
        return None
    u = str(unit or "").replace(" ", "")
    if field == "construction_cost_krw":
        factors = {"원": 1, "KRW": 1, "만원": 10000, "억원": 100000000, "조원": 1000000000000}
    elif field in ("building_area_m2", "gross_floor_area_m2"):
        factors = {"㎡": 1, "m²": 1, "m2": 1, "제곱미터": 1}
    elif field == "height_m":
        factors = {"m": 1, "미터": 1, "cm": .01, "센티미터": .01}
    else:
        factors = {BASE_UNITS.get(field, ""): 1}
    normalized = n * factors[u] if u in factors else None
    return normalized if normalized is not None and math.isfinite(normalized) else None


def _compare(actual: float, operator: str, threshold: float) -> bool:
    return {">=": actual >= threshold, ">": actual > threshold, "<=": actual <= threshold, "<": actual < threshold, "==": actual == threshold}[operator]


def _date(value: Any) -> str | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _extract_dates(text: str) -> list[dict[str, str]]:
    out = []
    pattern = re.compile(r"(?P<year>20\d{2})(?:\s*년\s*|[-./])(?P<month>\d{1,2})(?:\s*월\s*|[-./])(?P<day>\d{1,2})(?:\s*일)?")
    for match in pattern.finditer(text):
        try:
            value = dt.date(*(int(match[k]) for k in ("year", "month", "day"))).isoformat()
        except ValueError:
            continue
        context = text[max(0, match.start() - 28):match.end() + 36]
        kind = "시행일 후보" if re.search(r"시행|적용", context) else "공포일 후보" if "공포" in context else "날짜 후보"
        item = {"date": value, "kind": kind, "text": context.strip()}
        if item not in out:
            out.append(item)
    return out


def _term_found(term: str, text: str) -> bool:
    if re.fullmatch(r"[A-Za-z]+", term):
        return bool(re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", text, re.I))
    return term in text


def _clauses(text: str) -> list[str]:
    # Do not split decimal values, Article numbers or numeric dates at their dots.
    return [x.strip() for x in re.split(r"\n|[。!?]|(?<!\d)\.(?!\d)|;", text) if x.strip()]


def _topic_thresholds(topic: Topic, thresholds: list[dict], topic_count: int) -> list[dict]:
    if topic_count <= 1:
        return thresholds
    compatible = {
        "headcount": {"workforce", "risk", "contractor", "medical", "measurement"},
        "contractor_workers": {"workforce", "risk", "contractor", "construction"},
        "construction_cost_krw": {"construction", "workforce", "risk", "contractor"},
        "building_area_m2": {"building", "fire", "construction", "dangerousgoods"},
        "gross_floor_area_m2": {"building", "fire", "construction", "dangerousgoods"},
        "ground_floors": {"building", "fire", "construction"},
        "basement_floors": {"building", "fire", "construction"},
        "height_m": {"building", "fire", "construction", "height"},
    }
    return [x for x in thresholds if topic.id in compatible.get(x["field"], set())]


def _thresholds(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract only explicit field/unit/operator triples from an individual clause."""
    out: list[dict[str, Any]] = []
    issues: list[str] = []
    labels = (
        ("contractor_workers", r"(?:수급인|협력업체|협력사)\s*(?:소속\s*)?(?:근로자|종사자)(?:\s*수)?", r"명"),
        ("headcount", r"(?:상시\s*근로자|상시\s*종사자)(?:\s*수)?", r"명"),
        ("gross_floor_area_m2", r"연면적", r"(?:제곱미터|㎡|m²|m2)"),
        ("building_area_m2", r"건축면적", r"(?:제곱미터|㎡|m²|m2)"),
        ("construction_cost_krw", r"(?:총\s*)?공사\s*금액", r"(?:조원|억원|만원|원)"),
        ("ground_floors", r"지상\s*(?:층수|층)?", r"층"),
        ("basement_floors", r"지하\s*(?:층수|층)?", r"층"),
        ("height_m", r"(?:건축물(?:의)?\s*)?높이", r"(?:센티미터|미터|cm|m)"),
    )
    for field, label, unit_pattern in labels:
        marker = re.search(label, text, re.I)
        if not marker:
            continue
        # Restrict extraction to this label's measurement so different fields do not bleed together.
        remainder = text[marker.end():]
        other_positions = [m.start() for f, l, _ in labels if f != field for m in [re.search(l, remainder, re.I)] if m]
        if other_positions:
            remainder = remainder[:min(other_positions)]
        measurement = re.compile(r"(?P<number>" + NUMBER + r")\s*(?P<unit>" + unit_pattern + r")\s*(?:인\s*|의\s*)?(?P<op>" + OP_PATTERN + r")?", re.I)
        matches = list(measurement.finditer(remainder))
        if not matches:
            continue
        change_context = bool(re.search(r"종전|개정\s*(?:전|후)|→|변경|축소|확대", text))
        chosen = matches
        before = None
        if len(matches) >= 2 and change_context:
            bridge = remainder[matches[0].end():matches[-1].start()]
            if re.search(r"→|개정\s*후|변경", bridge) or (re.fullmatch(r"\s*에서\s*", bridge) and re.search(r"으로|로\s*(?:변경|축소|확대)", remainder[matches[-1].end():])):
                chosen = [matches[-1]]
                before = _normalise_numeric(field, matches[0]["number"], matches[0]["unit"])
                if not chosen[0]["op"]:
                    issues.append(f"{FIELD_LABELS[field]}의 종전→개정 수치는 있으나 개정 후 비교 조건이 명확하지 않습니다.")
                    continue
            else:
                issues.append(f"{FIELD_LABELS[field]}의 종전값과 개정값을 문장만으로 구별하기 어렵습니다.")
                continue
        for match in chosen:
            if not match["op"]:
                issues.append(f"{FIELD_LABELS[field]} 수치에 이상·미만 등의 명시적 비교 조건이 없습니다.")
                continue
            normalized = _normalise_numeric(field, match["number"], match["unit"])
            if normalized is None:
                issues.append(f"{FIELD_LABELS[field]}의 단위를 정규화할 수 없습니다.")
                continue
            threshold = {"field": field, "label": FIELD_LABELS[field], "operator": COMPARATORS[match["op"]], "value": normalized, "unit": BASE_UNITS[field], "source_text": match.group(0), "origin": "원문 수치 추출"}
            if before is not None:
                threshold["before"] = before
            out.append(threshold)
    if re.search(r"(?:바닥면적|면적)\s*(?:이|은|가|:)?\s*" + NUMBER, text) and not any(x["field"] in ("gross_floor_area_m2", "building_area_m2") for x in out):
        issues.append("면적의 산정 기준(연면적·건축면적·해당 용도 바닥면적)을 확인해야 합니다.")
    if re.search(r"(?:층수|층\s*이)\s*(?:가|는|:)?\s*" + NUMBER, text) and not any(x["field"] in ("ground_floors", "basement_floors") for x in out):
        issues.append("층수의 산정 기준(지상·지하·전체 또는 해당 용도)을 확인해야 합니다.")
    return out, list(dict.fromkeys(issues))


def _timing(document: dict, dates: list[dict], excerpt: str = "", specific_date: str | None = None) -> str:
    status = document.get("publication_status", "상태 미확인")
    today = _date(document.get("analysis_date")) or dt.date.today().isoformat()
    effective = _date(specific_date) or _date(document.get("effective_on"))
    if not effective:
        local_dates = _extract_dates(excerpt) if excerpt else dates
        candidates = sorted({x["date"] for x in local_dates if x["kind"] == "시행일 후보"})
        if len(candidates) == 1:
            effective = candidates[0]
    if status == "입법예고":
        return "입법예고: 확정 전 준비 검토 대상" + (f" · 제안된 시행일 {effective}" if effective else "")
    if status == "국회 법률안":
        return "국회 법률안: 가결·공포 여부 확인 필요" + (f" · 제안된 시행일 {effective}" if effective else "")
    if status not in ("현행 법령", "공포·시행 예정"):
        return "공포·시행 상태 미확인: 적용 시점을 확정할 수 없음"
    published = _date(document.get("published_on"))
    if published and published > today:
        return f"문서 상태·공포일 입력 충돌: 공포일 {published}이 분석 기준일보다 미래임 · 확인 필요"
    if effective and published and effective < published:
        return f"공포일·시행일 입력 순서 확인 필요: 공포일 {published}, 시행일 {effective} · 소급·경과 규정 원문 확인"
    if effective:
        return f"시행 예정: {effective}" if effective > today else f"입력 시행일 도래: {effective} · 조항별 경과조치 확인 필요"
    if status == "현행 법령":
        return "현행 법령으로 입력됨: 해당 변경 조항의 시행일·경과조치 확인 필요"
    return "공포·시행 예정으로 입력됨: 조항별 시행일 확인 필요"


def _profile_matches(profile: dict, topic: Topic) -> tuple[list[str], list[str], bool | None]:
    evidence: list[str] = []
    missing: list[str] = []
    states: list[bool] = []
    for field in topic.fields:
        value = profile.get(field)
        if type(value) is bool:
            states.append(value)
            evidence.append(f"{FIELD_LABELS.get(field, field)}: {'있음/대상으로 입력' if value else '없음/비대상으로 입력'}")
        else:
            missing.append(field)
    selected = profile.get("processes")
    if topic.processes and isinstance(selected, list) and any(p in selected for p in topic.processes):
        states.append(True)
        evidence.append("관련 공정 입력: " + ", ".join(PROCESS_LABELS.get(p, p) for p in selected if p in topic.processes))
    if topic.id == "construction" and profile.get("site_kind") == "건설·신축 현장":
        states.append(True)
        evidence.append("사업장 유형: 건설·신축 현장")
    # An inventory only supplies relevance; it never establishes a statutory classification.
    if topic.id == "chemical":
        inventory = profile.get("chemicals")
        if isinstance(inventory, list) and inventory:
            states.append(True)
            evidence.append("화학물질 목록이 입력됨: 법적 분류는 원문·공식 목록 확인 필요")
        elif True not in states:
            missing.append("chemicals")
    if topic.id == "dangerousgoods" and True not in states:
        # Having no licensed facility does not prove that no dangerous goods are handled.
        missing.append("chemicals")
    state = True if True in states else False if states and not missing else None
    if state is True:
        # A positive signal proves relevance even if another optional signal is unfilled.
        missing = []
    return evidence, missing, state


def _assess(profile: dict, topic: Topic, excerpt: str, thresholds: list[dict], issues: list[str], document: dict, dates: list[dict], result_id: str, terms: list[str], extra_fields: list[str] | None = None, specific_date: str | None = None) -> dict:
    evidence, missing, signal = _profile_matches(profile, topic)
    numeric_states: list[bool] = []
    thresholds = [dict(item) for item in thresholds]
    for target in thresholds:
        field = target["field"]
        value = profile.get(field)
        if field in BOOL_FIELDS:
            if type(value) is not bool:
                missing.append(field)
                target["comparison"] = "미입력"
            else:
                state = value == target["value"]
                numeric_states.append(state)
                target["comparison"] = "기준에 해당" if state else "기준에 해당하지 않음"
                evidence.append(f"{FIELD_LABELS.get(field, field)}: {value}")
            continue
        actual = _number(value)
        if actual is None:
            missing.append(field)
            target["comparison"] = "미입력 또는 잘못된 입력"
        else:
            state = _compare(actual, target["operator"], target["value"])
            numeric_states.append(state)
            target["comparison"] = "수치 조건 충족" if state else "수치 조건 미충족"
            evidence.append(f"{FIELD_LABELS.get(field, field)}: {actual:g}{BASE_UNITS.get(field, '')} {target['operator']} {target['value']:g}{target.get('unit', '')} → {'충족' if state else '미충족'}")
    for field in extra_fields or []:
        if profile.get(field) is None:
            missing.append(field)
    exception = bool(re.search(r"(?:제외|면제|해당하지|않|아니|아닌|아닐|없(?:는|은|다)|관계없이|무관하게|불문|상관없이|다만|단서|예외)", excerpt))
    if exception:
        issues = [*issues, "단서·예외·부정 표현이 포함되어 적용 범위를 추가로 확인해야 합니다."]
    if numeric_states:
        # Conditions from different fields can be alternatives or cumulative. Do not guess.
        if all(numeric_states):
            decision = "관련성 확인"
        elif len(numeric_states) == 1 and not any(numeric_states):
            decision = "현재 정보상 비대상"
        else:
            decision = "추가 확인"
            issues = [*issues, "복수 수치 조건을 모두 충족하지 않습니다. ‘및/또는’의 연결 대상과 단서·예외를 원문에서 확인해야 합니다."]
        # Numeric criteria are necessary even when a broad related process was selected.
        if len(numeric_states) != len(thresholds) or missing:
            decision = "추가 확인"
    elif signal is True:
        decision = "관련성 확인"
    elif signal is False:
        decision = "현재 정보상 비대상"
    else:
        decision = "추가 확인"
    if issues or missing:
        decision = "추가 확인"
    actions = list(topic.actions)
    actions.extend(issues)
    if missing:
        actions.append("미확인 제원 입력: " + ", ".join(FIELD_LABELS.get(x, x) for x in dict.fromkeys(missing)))
    actions.append(COMMON_ACTION)
    return {"id": result_id, "title": topic.title, "matched_terms": terms, "quote": excerpt, "profile_evidence": list(dict.fromkeys(evidence)), "applicability": decision, "timing": _timing(document, dates, excerpt, specific_date), "actions": list(dict.fromkeys(actions)), "missing_fields": list(dict.fromkeys(missing)), "thresholds": thresholds}


def _structured(document: dict, profile: dict, dates: list[dict]) -> tuple[list[dict], list[str]]:
    results, warnings = [], []
    changes = document.get("changes") or []
    if not isinstance(changes, list):
        return [], ["구조화된 변경사항은 목록 형식이어야 합니다."]
    for index, change in enumerate(changes, 1):
        if not isinstance(change, dict):
            warnings.append(f"변경사항 {index}: 올바른 항목 형식이 아닙니다.")
            continue
        field = str(change.get("field", ""))
        title = str(change.get("topic") or FIELD_LABELS.get(field, "입력 변경사항"))
        excerpt = str(change.get("source_excerpt") or "")
        operator = COMPARATORS.get(str(change.get("operator", "")))
        unit = str(change.get("unit", ""))
        after = change.get("after")
        numeric = _normalise_numeric(field, after, unit) if field in BASE_UNITS else None
        issue = []
        if field in BOOL_FIELDS and type(after) is bool and operator == "==":
            threshold = {"field": field, "label": FIELD_LABELS.get(field, field), "operator": "==", "value": after, "unit": "", "origin": "검토자 입력 기준"}
        elif numeric is not None and operator:
            threshold = {"field": field, "label": FIELD_LABELS.get(field, field), "operator": operator, "value": numeric, "unit": BASE_UNITS[field], "origin": "검토자 입력 기준"}
            before = _normalise_numeric(field, change.get("before"), unit)
            if before is not None:
                threshold["before"] = before
        else:
            threshold = None
            issue.append("입력 변경 기준의 항목·단위·비교식·개정 후 값을 확인하세요.")
        if not excerpt:
            issue.append("변경사항의 공식 원문 발췌를 입력하고 변경 기준과 대조하세요.")
        # Avoid optional topic signals obscuring a reviewed explicit target.
        topic = Topic("structured", title, str(document.get("law_family", "전체")), ())
        result = _assess(profile, topic, excerpt, [threshold] if threshold else [], issue, document, dates, f"change-{index}", [title], [field] if field and not threshold else [], _date(change.get("effective_on")))
        results.append(result)
    return results, warnings


def analyze_amendment(profile: dict, document: dict) -> dict:
    """Return transparent relevance signals and missing data, not legal obligations.

    profile quantities use base units (people, KRW, m², floors, metres).
    changes may contain reviewer-confirmed topic/field/operator/before/after/unit,
    effective_on/source_excerpt entries; their source excerpt is still displayed.
    """
    text = str(document.get("text") or "").strip()
    title = str(document.get("title") or "제목 없는 검토 문서")
    family = str(document.get("law_family") or "전체")
    warnings = ["이 결과는 입력 원문과 제원을 대조한 관련성 검토입니다. 법적 적용 여부는 조항·별표·경과조치 검토로 확정해야 합니다."]
    if not document.get("source_url"):
        warnings.append("공식 원문 URL이 없습니다. 문서 출처와 최신 버전을 확인하세요.")
    status = str(document.get("publication_status") or "상태 미확인")
    if status in ("입법예고", "국회 법률안"):
        warnings.append(f"{status} 문서는 확정된 현행 의무로 취급하지 않습니다. 가결·공포·시행 여부를 확인하세요.")
    elif status not in ("현행 법령", "공포·시행 예정"):
        warnings.append("문서의 공포·시행 상태가 확인되지 않아 적용 의무나 시점을 확정할 수 없습니다.")
    for field, label in (("published_on", "공포일"), ("effective_on", "시행일"), ("analysis_date", "분석 기준일")):
        if document.get(field) and not _date(document[field]):
            warnings.append(f"{label} 형식을 확인하세요(YYYY-MM-DD).")
    if not _date(document.get("analysis_date")):
        warnings.append("분석 기준일이 없거나 유효하지 않아 실행일을 기준으로 시행 시점을 표시했습니다.")
    today = _date(document.get("analysis_date")) or dt.date.today().isoformat()
    published = _date(document.get("published_on"))
    effective = _date(document.get("effective_on"))
    date_conflict = False
    if status in ("현행 법령", "공포·시행 예정") and published and published > today:
        date_conflict = True
        warnings.append("확정된 법령으로 입력했지만 공포일이 분석 기준일보다 미래입니다. 문서 상태 또는 날짜를 다시 확인하세요.")
    if published and effective and effective < published:
        date_conflict = True
        warnings.append("입력 시행일이 공포일보다 앞섭니다. 날짜 입력과 소급·경과 규정 원문을 확인하세요.")
    dates = _extract_dates(text)
    results, structured_warnings = _structured(document, profile, dates)
    warnings.extend(structured_warnings)
    clauses = _clauses(text)
    if not clauses and not results:
        warnings.append("분석할 원문이나 검토자가 입력한 변경사항이 없습니다.")
    for clause_index, clause in enumerate(clauses, 1):
        thresholds, issues = _thresholds(clause)
        matched = [(topic, [term for term in topic.terms if _term_found(term, clause)]) for topic in TOPICS]
        matched = [(topic, terms) for topic, terms in matched if terms]
        # A selected family narrows suggestions, while explicit cross-law source terms
        # remain visible; related clauses must not disappear merely because of a filter.
        for topic, terms in matched:
            if topic.id == "risk" and len(matched) > 1 and all(term in ("산업안전보건", "중대재해") for term in terms):
                continue
            extra = []
            if topic.id == "workforce" and not thresholds:
                extra = ["headcount"]
            targeted = _topic_thresholds(topic, thresholds, len(matched))
            result = _assess(profile, topic, clause, targeted, issues, document, dates, f"clause-{clause_index}-{topic.id}", terms, extra)
            if family != "전체" and family != topic.family:
                result["actions"].insert(0, f"선택 법령 분야({family})와 연결된 {topic.family} 조항인지 원문에서 확인하세요.")
            results.append(result)
        if thresholds and not matched:
            generic = Topic("numeric", "수치 기준의 적용 범위", family, ())
            results.append(_assess(profile, generic, clause, thresholds, issues, document, dates, f"clause-{clause_index}-numeric", [], []))
    if not results:
        warnings.append("인식된 관련 주제가 없습니다. 키워드 부재는 영향 없음의 근거가 아니므로 원문 조항을 직접 검토하거나 구조화된 변경사항을 추가하세요.")
    counts = {name: sum(r["applicability"] == name for r in results) for name in ("관련성 확인", "추가 확인", "현재 정보상 비대상")}
    has_review = not results or bool(counts["추가 확인"]) or date_conflict or status not in ("현행 법령", "공포·시행 예정")
    summary = f"{title}: 관련성 확인 {counts['관련성 확인']}건 · 추가 확인 {counts['추가 확인']}건 · 현재 정보상 비대상 {counts['현재 정보상 비대상']}건. "
    summary += "문서의 확정 여부와 시행 시점을 구분해 검토하세요." if status in ("입법예고", "국회 법률안", "상태 미확인") else "각 결과의 원문 근거와 누락 제원을 확인하세요."
    return {"summary": summary, "status": "추가 검토 필요" if has_review else "원문 대조 결과 확인", "warnings": list(dict.fromkeys(warnings)), "results": results, "extracted_dates": dates}
