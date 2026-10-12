"""사업장 입력 스키마. 미입력과 실제 0/아니오를 구분한다."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import uuid

SCHEMA_VERSION = 2
PROCESS_OPTIONS = {
    "cleanroom": "클린룸·청정공정",
    "wet_chemical": "습식세정·에칭·도금·약품 혼합",
    "press": "프레스·절단·성형",
    "machining": "절삭·연마·가공",
    "assembly": "조립·자동화·로봇",
    "welding": "용접·용단·화기작업",
    "painting": "도장·코팅·유기용제",
    "heat_treatment": "열처리·건조·가열",
    "food": "식품·음료 제조·세척",
    "logistics": "창고·하역·지게차·물류",
    "utility": "보일러·유틸리티·폐수처리",
    "battery": "배터리·충전·에너지저장",
    "construction": "건설·신축·대수선",
}

_TEMPLATES = {
    "cleanroom": ("반도체·디스플레이 클린룸", "제조 사업장", "반도체·디스플레이", ["cleanroom", "wet_chemical", "utility"]),
    "pcb": ("PCB·전자기판", "제조 사업장", "PCB·전자부품", ["wet_chemical", "machining", "assembly", "utility"]),
    "press": ("프레스·금속 성형", "제조 사업장", "금속·자동차부품", ["press", "machining", "logistics"]),
    "machining": ("기계가공·베어링", "제조 사업장", "기계·정밀부품", ["machining", "heat_treatment", "assembly"]),
    "assembly": ("조립·자동화", "제조 사업장", "기계·전자 조립", ["assembly", "logistics"]),
    "welding": ("용접·제관", "제조 사업장", "금속·구조물", ["welding", "painting", "logistics"]),
    "surface": ("도금·표면처리·코팅", "제조 사업장", "표면처리", ["wet_chemical", "painting", "utility"]),
    "chemical": ("화학·혼합·배합", "제조 사업장", "화학제품", ["wet_chemical", "heat_treatment", "logistics"]),
    "heat": ("열처리·건조", "제조 사업장", "열처리·가열", ["heat_treatment", "machining"]),
    "food": ("식품·음료", "제조 사업장", "식품·음료", ["food", "utility", "logistics"]),
    "battery": ("배터리·충전·ESS", "제조 사업장", "배터리·에너지", ["battery", "wet_chemical", "assembly"]),
    "warehouse": ("물류·창고", "제조 사업장", "물류·보관", ["logistics"]),
    "utility": ("유틸리티·폐수처리", "제조 사업장", "유틸리티", ["utility"]),
    "new_factory": ("공장 신축 현장", "건설·신축 현장", "공장 신축", ["construction"]),
    "construction": ("일반 건설·대수선 현장", "건설·신축 현장", "건설·대수선", ["construction", "welding"]),
}
TEMPLATE_OPTIONS = {key: value[0] for key, value in _TEMPLATES.items()}


def _number(label, group, unit="", kind="float", step=1):
    return {"label": label, "group": group, "unit": unit, "type": kind, "step": step}


NUMERIC_FIELDS = {
    "headcount": _number("상시근로자 수", "인원·운영", "명", "int"),
    "contractor_workers": _number("현장 도급·수급인 근로자 수", "인원·운영", "명", "int"),
    "daily_max_people": _number("최대 동시 재실 인원", "인원·운영", "명", "int"),
    "daily_shifts": _number("일일 교대조 수", "인원·운영", "조", "int"),
    "building_area_m2": _number("전체 건축면적(건물 바닥 투영면적 합계)", "건축·소방", "㎡", step=10),
    "gross_floor_area_m2": _number("전체 연면적(각 층 면적 합계)", "건축·소방", "㎡", step=10),
    "ground_floors": _number("최대 지상 층수", "건축·소방", "층", "int"),
    "basement_floors": _number("최대 지하 층수", "건축·소방", "층", "int"),
    "height_m": _number("최대 건물 높이", "건축·소방", "m", step=0.5),
    "fire_compartment_area_m2": _number("확인할 방화구획 면적", "건축·소방", "㎡", step=10),
    "flammable_liquid_l": _number("인화성 액체 최대 저장량", "물질·가스", "L", step=10),
    "dangerous_goods_multiple": _number("허가·품명 기준으로 확인한 지정수량 배수", "물질·가스", "배", step=0.1),
    "gas_storage_kg": _number("가스 최대 저장 질량", "물질·가스", "kg", step=10),
    "tank_volume_m3": _number("최대 탱크 용량", "물질·가스", "㎥", step=0.1),
    "press_capacity_t": _number("프레스 최대 정격능력", "설비·작업", "ton", step=1),
    "crane_capacity_t": _number("크레인 최대 정격하중", "설비·작업", "ton", step=0.1),
    "forklift_count": _number("지게차 대수", "설비·작업", "대", "int"),
    "pressure_vessel_volume_m3": _number("압력용기 최대 용적", "설비·작업", "㎥", step=0.01),
    "max_pressure_mpa": _number("설비 최대 사용압력", "설비·작업", "MPa", step=0.01),
    "boiler_capacity_tph": _number("보일러 최대 증발량", "설비·작업", "ton/h", step=0.1),
    "electrical_capacity_kw": _number("수전·전기설비 용량", "설비·작업", "kW", step=10),
    "max_work_height_m": _number("최대 고소작업 높이", "설비·작업", "m", step=0.5),
    "max_storage_height_m": _number("최대 적재 높이", "설비·작업", "m", step=0.1),
    "noise_db_a": _number("확인된 소음 측정값", "설비·작업", "dB(A)", step=0.1),
    "construction_cost_krw": _number("총공사금액", "건설·신축", "원", step=10000000),
    "construction_duration_months": _number("공사 기간", "건설·신축", "개월", "int"),
    "excavation_depth_m": _number("최대 굴착 깊이", "건설·신축", "m", step=0.1),
    "construction_floor_area_m2": _number("해당 신축·증축 공사 연면적", "건설·신축", "㎡", step=10),
    "wastewater_m3_day": _number("폐수 발생·배출량", "환경", "㎥/일", step=0.1),
    "air_emission_stack_count": _number("대기 배출구 수", "환경", "개", "int"),
    "designated_waste_kg_month": _number("지정폐기물 발생량", "환경", "kg/월", step=10),
}

FLAG_FIELDS = {
    "confined_space": {"label": "밀폐공간·탱크·맨홀 작업", "group": "작업 위험"},
    "work_at_height": {"label": "고소·추락 위험 작업", "group": "작업 위험"},
    "excavation": {"label": "굴착·흙막이 작업", "group": "작업 위험"},
    "lifting_work": {"label": "양중·하역 작업", "group": "작업 위험"},
    "hot_work": {"label": "용접·용단 등 화기작업", "group": "작업 위험"},
    "flammable_atmosphere": {"label": "인화성 가스·증기·분진에 따른 폭발 위험", "group": "작업 위험"},
    "hazardous_chemicals": {"label": "화학물질관리법상 유해화학물질 취급 확인", "group": "물질·가스"},
    "msds_target": {"label": "MSDS 대상물질 취급 확인", "group": "물질·가스"},
    "special_health_exam_target": {"label": "특수건강진단 대상 유해인자 확인", "group": "보건"},
    "work_environment_measurement_target": {"label": "작업환경측정 대상 유해인자 확인", "group": "보건"},
    "psm_confirmed": {"label": "PSM 대상 여부를 업종·물질·수량 기준으로 확인", "group": "공정·설비"},
    "dangerous_goods_facility": {"label": "위험물 제조소·저장소·취급소 해당 확인", "group": "물질·가스"},
    "dangerous_machines": {"label": "유해·위험기계 사용", "group": "공정·설비"},
    "compressed_gas": {"label": "고압·압축·액화가스 설비", "group": "물질·가스"},
    "contractor_work": {"label": "도급·수급인 작업", "group": "인원·운영"},
    "shift_work": {"label": "교대·야간작업", "group": "인원·운영"},
    "combustible_storage": {"label": "가연성 제품·포장재·재료 저장", "group": "건축·소방"},
    "wastewater_discharge": {"label": "폐수배출시설 운영·설치", "group": "환경"},
    "air_emission_facility": {"label": "대기배출시설 운영·설치", "group": "환경"},
    "designated_waste": {"label": "지정폐기물 발생 확인", "group": "환경"},
    "construction_project": {"label": "건설공사 진행", "group": "건설·신축"},
    "new_building": {"label": "신축·증축", "group": "건설·신축"},
    "permit_change": {"label": "용도변경·대수선·인허가 변경", "group": "건설·신축"},
    "worker_accommodation": {"label": "근로자 숙소·기숙사", "group": "건축·소방"},
    "asbestos_work": {"label": "석면 조사·해체 관련 공사", "group": "건설·신축"},
    "robot_work": {"label": "산업용 로봇 사용", "group": "공정·설비"},
    "electrical_work": {"label": "전기설비 점검·정비 작업", "group": "작업 위험"},
    "temporary_electricity": {"label": "가설 전기·임시 배전", "group": "건설·신축"},
    "sand_dust_work": {"label": "분진 발생 작업", "group": "보건"},
    "organic_solvents": {"label": "유기용제 사용", "group": "물질·가스"},
    "noise_work": {"label": "소음 발생 작업", "group": "보건"},
    "refrigeration_ammonia": {"label": "암모니아 냉동설비", "group": "물질·가스"},
    "food_hygiene_target": {"label": "식품 제조·위생관리 대상", "group": "공정·설비"},
    "fire_system_present": {"label": "설치된 소방시설 보유", "group": "건축·소방"},
}
TEXT_FIELDS = {
    "name": {"label": "사업장 이름", "group": "기본 정보"},
    "industry_name": {"label": "업종·생산품", "group": "기본 정보"},
    "ksic_code": {"label": "한국표준산업분류 코드", "group": "기본 정보"},
    "location": {"label": "사업장 소재지", "group": "기본 정보"},
    "site_kind": {"label": "사업장 구분", "group": "기본 정보", "options": ["제조 사업장", "건설·신축 현장", "미확인"]},
    "building_use": {"label": "주요 건축물 용도", "group": "건축·소방", "options": ["미확인", "공장", "창고", "연구시설", "업무시설", "복합용도", "기숙사", "기타"]},
    "building_structure": {"label": "주요 구조", "group": "건축·소방", "options": ["미확인", "철근콘크리트", "철골", "철골철근콘크리트", "목구조", "복합구조", "기타"]},
    "permit_status": {"label": "건축 인허가 상태", "group": "건설·신축", "options": ["미확인", "계획·검토", "허가·신고 전", "허가·신고 완료", "공사 중", "사용승인 완료"]},
    "profile_notes": {"label": "공정·허가·분류 관련 메모", "group": "기본 정보"},
}


def _missing(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in ("", "미확인", "미입력", "알 수 없음")
    try:
        if isinstance(value, float):
            return not math.isfinite(value)
        if type(value).__name__ in ("NAType", "NaTType"):
            return True
    except (TypeError, ValueError):
        return True
    return False


def _numeric(value, kind="float"):
    if _missing(value) or isinstance(value, bool):
        return None
    try:
        numeric = float(str(value).replace(",", ""))
        if not math.isfinite(numeric) or numeric < 0:
            return None
        if kind == "int":
            return int(numeric) if numeric.is_integer() else None
        return numeric
    except (TypeError, ValueError):
        return None


def _flag(value):
    if value is None or _missing(value):
        return None
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in ("true", "예", "해당", "yes"):
        return True
    if str(value).strip().lower() in ("false", "아니오", "비해당", "no"):
        return False
    return None


def empty_profile(name="새 사업장"):
    profile = {"uid": str(uuid.uuid4()), "schema_version": SCHEMA_VERSION,
               "name": name, "template_id": "", "processes": [],
               "buildings": [], "chemicals": [], "equipment": [],
               "template_is_example": False, "demo_is_example": False,
               "demo_id": "", "demo_description": "", "demo_learning_points": [],
               "updated_at": ""}
    profile.update({key: None for key in NUMERIC_FIELDS})
    profile.update({key: None for key in FLAG_FIELDS})
    profile.update({key: "" for key in TEXT_FIELDS if key != "name"})
    profile["site_kind"] = "미확인"
    profile["building_use"] = "미확인"
    return profile


def get_template(template_id):
    if template_id not in _TEMPLATES:
        return empty_profile()
    label, kind, industry, processes = _TEMPLATES[template_id]
    profile = empty_profile(label + " 예제")
    profile.update(template_id=template_id, site_kind=kind, industry_name=industry,
                   processes=[item for item in processes if item in PROCESS_OPTIONS],
                   template_is_example=True,
                   profile_notes="공정 구성을 제안하는 예제입니다. 실제 인원·제원·물질 분류·작업 위험은 확인 후 입력하세요.")
    return profile


def get_demo_profiles():
    """Return independent, populated fictional workplaces; demo_id is stable for merging.

    Values describe learning scenarios rather than actual companies or legal findings.
    The function is self-contained so hosted apps need no separate example JSON file.
    """
    def building(name, use, structure, gross, footprint, floors, height, permit="사용승인 완료"):
        return {"name": name, "use": use, "structure": structure,
                "gross_floor_area_m2": gross, "building_area_m2": footprint,
                "ground_floors": floors, "basement_floors": 0, "height_m": height,
                "permit_status": permit}

    def chemical(name, storage_l, daily_kg, annual_kg, note):
        return {"name": name, "cas": "", "physical_state": "액체",
                "concentration_pct": None, "max_storage_kg": None,
                "max_storage_l": storage_l, "daily_use_kg": daily_kg,
                "annual_use_kg": annual_kg, "hazard_classes": "제품별 SDS·법정 분류 확인 필요",
                "classification_verified": None, "notes": "가상 제품·가정 수량. " + note}

    def equipment(kind, name, quantity, capacity, unit, location):
        return {"kind": kind, "name": name, "quantity": quantity,
                "rated_capacity": capacity, "capacity_unit": unit,
                "inspection_status": "제조번호·검사대장·증빙 확인 필요", "location": location}

    shared_notes = (
        "실재 회사와 무관한 가상 시연용 제원입니다. 인원·수량·예/아니오는 학습을 위한 가정이며 "
        "실제 법적 적용 판정이 아닙니다. PSM·위험물·유해화학물질·보건 대상 등은 "
        "업종, 제품별 SDS, 농도·수량, 허가서, 측정자료로 확인해야 하므로 미확인으로 남겼습니다. "
        "실제 사업장에 사용하려면 예제 이름과 입력값을 실제 자료로 바꾸세요."
    )
    specs = [
        {
            "demo_id": "pcb", "name": "[가상 예제] PCB 습식공정 공장", "template_id": "pcb",
            "demo_description": "에칭·세정 공정과 폐수처리시설이 있는 전자기판 공장입니다. 약품·밀폐공간·도급 작업을 함께 검토하는 흐름을 보여줍니다.",
            "demo_learning_points": ["약품명만으로 법적 분류를 확정하지 않는 방법", "생산동과 유틸리티동의 개별 제원 확인", "폐수조 정비와 도급 작업의 확인자료 찾기"],
            "industry_name": "가상 전자기판 제조 / 습식 에칭·세정·가공·조립",
            "building_use": "공장", "building_structure": "복합구조", "permit_status": "사용승인 완료",
            "headcount": 120, "contractor_workers": 15, "daily_max_people": 85, "daily_shifts": 2,
            "building_area_m2": 5500, "gross_floor_area_m2": 8500, "ground_floors": 2,
            "basement_floors": 0, "height_m": 12, "tank_volume_m3": 6,
            "forklift_count": 2, "electrical_capacity_kw": 2500, "max_work_height_m": 4,
            "max_storage_height_m": 2.5, "wastewater_m3_day": 180, "air_emission_stack_count": 3,
            "designated_waste_kg_month": 1200,
            "confined_space": True, "work_at_height": True, "lifting_work": True,
            "contractor_work": True, "shift_work": True, "msds_target": True,
            "wastewater_discharge": True, "air_emission_facility": True, "designated_waste": True,
            "electrical_work": True, "combustible_storage": True, "fire_system_present": True,
            "construction_project": False, "new_building": False, "organic_solvents": False,
            "buildings": [building("가상 생산동", "공장", "철근콘크리트", 6000, 3000, 2, 12),
                          building("가상 유틸리티·폐수처리동", "공장", "철골", 2500, 2500, 1, 8)],
            "chemicals": [chemical("가상 산성 에칭액(혼합제품)", 6000, 200, 50000, "조성·농도·혼합물 CAS는 제품 SDS 확인 후 입력."),
                          chemical("가상 알칼리 세정액(혼합제품)", 1000, 40, 10000, "법정 분류와 취급시설 대상 여부는 별도 확인.")],
            "equipment": [equipment("공정 설비", "가상 습식 에칭 라인", 2, None, "", "생산동 1층"),
                          equipment("저장탱크", "가상 에칭액 저장탱크", 1, 6, "㎥", "약품실"),
                          equipment("폐수처리 설비", "가상 폐수처리 계통", 1, 180, "㎥/일", "유틸리티동"),
                          equipment("지게차", "가상 전동 지게차", 2, 2.5, "ton", "자재 입출고장")],
        },
        {
            "demo_id": "press", "name": "[가상 예제] 프레스·금속가공 공장", "template_id": "press",
            "demo_description": "프레스 성형과 기계가공, 자재 하역을 수행하는 자동차 부품 공장입니다. 설비의 정격·수량과 작업 위험을 연결해 봅니다.",
            "demo_learning_points": ["프레스·크레인 정격과 검사 증빙 입력", "소음 발생과 측정·건강진단 대상 확인의 구분", "지게차·보행자 이동 동선 검토"],
            "industry_name": "가상 금속 자동차부품 / 프레스 성형·절삭 가공",
            "building_use": "공장", "building_structure": "철골", "permit_status": "사용승인 완료",
            "headcount": 70, "contractor_workers": 5, "daily_max_people": 75, "daily_shifts": 1,
            "building_area_m2": 3000, "gross_floor_area_m2": 4000, "ground_floors": 2,
            "basement_floors": 0, "height_m": 12, "press_capacity_t": 200, "crane_capacity_t": 5,
            "forklift_count": 3, "pressure_vessel_volume_m3": 1, "max_pressure_mpa": 0.8,
            "electrical_capacity_kw": 1000, "max_storage_height_m": 3, "max_work_height_m": 3,
            "noise_db_a": 87,
            "dangerous_machines": True, "lifting_work": True, "noise_work": True,
            "compressed_gas": True, "contractor_work": True, "msds_target": True,
            "electrical_work": True, "fire_system_present": True, "combustible_storage": True,
            "construction_project": False, "new_building": False, "confined_space": False,
            "buildings": [building("가상 프레스·가공동", "공장", "철골", 4000, 3000, 2, 12)],
            "chemicals": [chemical("가상 수용성 절삭유(사용액)", 500, 10, 2500, "희석비와 공급 제품 SDS를 함께 확인. 소음 87 dB(A)는 측정값 입력 연습용 가정.")],
            "equipment": [equipment("프레스", "가상 기계식 프레스", 4, 200, "ton", "성형구역"),
                          equipment("크레인", "가상 천장크레인", 1, 5, "ton", "자재 투입구역"),
                          equipment("기계가공", "가상 CNC 가공기", 6, None, "", "가공구역"),
                          equipment("지게차", "가상 전동 지게차", 3, 3, "ton", "자재창고"),
                          equipment("압력용기", "가상 공기저장조", 1, 1, "㎥", "콤프레서실")],
        },
        {
            "demo_id": "food", "name": "[가상 예제] 식품·음료 공장", "template_id": "food",
            "demo_description": "음료 혼합·가열·충전과 용기 세척, 포장재 저장을 수행하는 공장입니다. 생산·위생과 보일러·폐수·화재 위험을 함께 살펴봅니다.",
            "demo_learning_points": ["식품공정과 유틸리티·폐수 작업의 함께 보기", "생산동과 포장재 창고의 건축물별 입력", "세척약품·보일러·물류 설비 목록 작성"],
            "industry_name": "가상 음료 제조 / 혼합·가열·충전·세척·포장",
            "processes": ["food", "heat_treatment", "utility", "logistics"],
            "building_use": "복합용도", "building_structure": "복합구조", "permit_status": "사용승인 완료",
            "headcount": 160, "contractor_workers": 20, "daily_max_people": 110, "daily_shifts": 2,
            "building_area_m2": 8000, "gross_floor_area_m2": 13000, "ground_floors": 2,
            "basement_floors": 0, "height_m": 12, "forklift_count": 4, "boiler_capacity_tph": 3,
            "max_pressure_mpa": 0.7, "electrical_capacity_kw": 1800, "tank_volume_m3": 10,
            "max_storage_height_m": 4, "max_work_height_m": 4, "wastewater_m3_day": 90,
            "food_hygiene_target": True, "combustible_storage": True, "wastewater_discharge": True,
            "contractor_work": True, "shift_work": True, "lifting_work": True,
            "msds_target": True, "confined_space": True, "work_at_height": True,
            "electrical_work": True, "fire_system_present": True, "refrigeration_ammonia": False,
            "construction_project": False, "new_building": False,
            "buildings": [building("가상 음료 생산동", "공장", "철근콘크리트", 10000, 5000, 2, 12),
                          building("가상 포장재 창고", "창고", "철골", 3000, 3000, 1, 10)],
            "chemicals": [chemical("가상 CIP 세척제(혼합제품)", 600, 20, 5000, "식품 원료와 구분해 약품 목록에 기록. 실제 농도·유해성은 SDS 확인.")],
            "equipment": [equipment("혼합탱크", "가상 음료 혼합탱크", 3, 10, "㎥", "생산동 1층"),
                          equipment("충전·포장", "가상 자동 충전 라인", 2, None, "", "생산동 1층"),
                          equipment("보일러", "가상 스팀보일러", 1, 3, "ton/h", "유틸리티실"),
                          equipment("지게차", "가상 전동 지게차", 4, 2.5, "ton", "포장재 창고")],
        },
        {
            "demo_id": "warehouse", "name": "[가상 예제] 일반 물류창고", "template_id": "warehouse",
            "demo_description": "상온의 일반 생활용품·포장재를 랙에 보관하고 지게차로 입출고하는 창고입니다. 제조 약품이 없는 장소의 입력 방식도 비교할 수 있습니다.",
            "demo_learning_points": ["창고 용도·높이·적재 높이를 구분해 입력", "지게차·랙·도크 작업 위험 확인", "확인한 비해당은 아니오, 모르는 대상 여부는 미확인으로 입력"],
            "industry_name": "가상 상온 생활용품 보관·입출고 / 제조공정 없음",
            "building_use": "창고", "building_structure": "철골", "permit_status": "사용승인 완료",
            "headcount": 35, "contractor_workers": 8, "daily_max_people": 43, "daily_shifts": 1,
            "building_area_m2": 6000, "gross_floor_area_m2": 6000, "ground_floors": 1,
            "basement_floors": 0, "height_m": 14, "forklift_count": 6,
            "electrical_capacity_kw": 450, "max_storage_height_m": 8, "max_work_height_m": 8,
            "lifting_work": True, "combustible_storage": True, "contractor_work": True,
            "work_at_height": True, "electrical_work": True, "fire_system_present": True,
            "msds_target": False, "organic_solvents": False, "confined_space": False,
            "wastewater_discharge": False, "air_emission_facility": False,
            "construction_project": False, "new_building": False,
            "buildings": [building("가상 상온 물류창고", "창고", "철골", 6000, 6000, 1, 14)],
            "chemicals": [],
            "equipment": [equipment("지게차", "가상 전동 지게차", 6, 2.5, "ton", "입출고장·랙 통로"),
                          equipment("저장 랙", "가상 팔레트 랙", 40, 8, "적재 높이(m)", "상온 보관구역"),
                          equipment("하역 설비", "가상 도크 레벨러", 4, None, "", "출하 도크")],
        },
        {
            "demo_id": "new_factory", "name": "[가상 예제] 공장 신축 현장", "template_id": "new_factory",
            "demo_description": "철골 공장동을 신축하는 120억 원 규모의 가상 공사입니다. 완공 후 공장 운영 조건과 공사 중 추락·굴착·양중 위험을 구분해 봅니다.",
            "demo_learning_points": ["공사금액·기간·굴착 깊이·작업 높이 입력", "공사 중 건물의 예정 제원과 인허가 상태 표시", "원도급·수급인 인원과 가설전기·화기작업 확인"],
            "industry_name": "가상 공장 신축 / 철골·기초·설비 설치 공사",
            "processes": ["construction", "welding", "logistics"],
            "building_use": "공장", "building_structure": "철골", "permit_status": "공사 중",
            "headcount": 90, "contractor_workers": 75, "daily_max_people": 165, "daily_shifts": 1,
            "building_area_m2": 5000, "gross_floor_area_m2": 10000, "ground_floors": 2,
            "basement_floors": 0, "height_m": 15, "construction_floor_area_m2": 10000,
            "construction_cost_krw": 12000000000, "construction_duration_months": 14,
            "excavation_depth_m": 3, "max_work_height_m": 15, "crane_capacity_t": 25,
            "forklift_count": 1, "electrical_capacity_kw": 150,
            "construction_project": True, "new_building": True, "work_at_height": True,
            "excavation": True, "lifting_work": True, "hot_work": True,
            "temporary_electricity": True, "contractor_work": True, "electrical_work": True,
            "sand_dust_work": True, "noise_work": True, "msds_target": True,
            "combustible_storage": True, "fire_system_present": True, "asbestos_work": False,
            "buildings": [building("가상 신축 공장동(완공 예정 제원)", "공장", "철골", 10000, 5000, 2, 15, "공사 중")],
            "chemicals": [chemical("가상 방수·실란트 제품", 120, 5, 1200, "제품별 용제 함유·법정 분류는 SDS로 확인. 연 사용량은 입력 연습을 위한 계획값.")],
            "equipment": [equipment("이동식 크레인", "가상 이동식 크레인", 1, 25, "ton", "철골 양중구역"),
                          equipment("고소작업대", "가상 고소작업대", 2, 15, "작업 높이(m)", "철골·지붕 시공구역"),
                          equipment("지게차", "가상 자재 지게차", 1, 3, "ton", "자재 적치장"),
                          equipment("가설 배전", "가상 임시 배전반", 3, None, "", "동별 임시 전원구역")],
        },
    ]
    result = []
    for spec in specs:
        profile = get_template(spec["template_id"])
        profile.update(spec)
        profile.update(uid="demo-" + spec["demo_id"], demo_is_example=True,
                       template_is_example=True, location="가상 산업단지·현장 (실재 주소 아님)",
                       profile_notes=shared_notes)
        result.append(normalize_profile(profile))
    return result


def normalize_profile(data):
    if not isinstance(data, dict):
        raise ValueError("사업장 프로필은 객체 형태여야 합니다.")
    profile = empty_profile(str(data.get("name") or "이름 없는 사업장"))
    for key in ("uid", "template_id", "updated_at"):
        if data.get(key):
            profile[key] = str(data[key])
    profile["template_is_example"] = _flag(data.get("template_is_example")) is True
    profile["demo_is_example"] = _flag(data.get("demo_is_example")) is True
    for key in ("demo_id", "demo_description"):
        if not _missing(data.get(key)):
            profile[key] = str(data[key]).strip()
    learning_points = data.get("demo_learning_points", [])
    if isinstance(learning_points, list):
        profile["demo_learning_points"] = [str(item).strip() for item in learning_points
                                           if isinstance(item, str) and item.strip()]
    for key in TEXT_FIELDS:
        if not _missing(data.get(key)):
            profile[key] = str(data[key]).strip()
    for key, spec in NUMERIC_FIELDS.items():
        profile[key] = _numeric(data.get(key), spec["type"])
    for key in FLAG_FIELDS:
        profile[key] = _flag(data.get(key))
    processes = data.get("processes", [])
    if not isinstance(processes, list):
        processes = []
    profile["processes"] = list(dict.fromkeys(item for item in processes if item in PROCESS_OPTIONS))
    for table in ("buildings", "chemicals", "equipment"):
        rows = data.get(table) or []
        if not isinstance(rows, list):
            rows = []
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            result = {}
            for key, value in row.items():
                if _missing(value):
                    result[str(key)] = None
                elif isinstance(value, (str, int, float, bool, list)):
                    result[str(key)] = deepcopy(value)
                else:
                    result[str(key)] = str(value)
            if not any(value is not None and value != "" for value in result.values()):
                continue
            numeric_columns = {
                "buildings": ["gross_floor_area_m2", "building_area_m2", "ground_floors", "basement_floors", "height_m"],
                "chemicals": ["concentration_pct", "max_storage_kg", "max_storage_l", "daily_use_kg", "annual_use_kg"],
                "equipment": ["quantity", "rated_capacity"],
            }[table]
            for key in numeric_columns:
                if key in result:
                    result[key] = _numeric(result[key], "int" if key in ("ground_floors", "basement_floors", "quantity") else "float")
            if table == "chemicals":
                result["classification_verified"] = _flag(result.get("classification_verified"))
            cleaned.append(result)
        profile[table] = cleaned
    profile["schema_version"] = SCHEMA_VERSION
    return profile


def validate_profile(profile):
    warnings = []
    if not profile.get("name"):
        warnings.append("사업장 이름이 필요합니다.")
    if not profile.get("processes"):
        warnings.append("공정을 선택하지 않아 공정별 관련성 검토가 제한됩니다.")
    if profile.get("headcount") is None:
        warnings.append("상시근로자 수가 미입력입니다. 인원 기준과 적용 예외를 추가 확인해야 합니다.")
    if profile.get("gross_floor_area_m2") is None:
        warnings.append("전체 연면적이 미입력입니다. 건축물별 상세표와 전체 제원을 확인하세요.")
    if len(profile.get("buildings", [])) > 1:
        warnings.append("복수 건물의 총면적·최대 층수는 각 건물별 적용 조건을 대신하지 않습니다.")
    for row in profile.get("chemicals", []):
        if row.get("concentration_pct") is not None and row["concentration_pct"] > 100:
            warnings.append(f"물질 '{row.get('name') or '이름 없음'}'의 농도는 0~100% 범위를 확인하세요.")
        if row.get("classification_verified") is not True:
            warnings.append(f"물질 '{row.get('name') or '이름 없음'}'의 법적 분류가 미확인입니다. 이름만으로 PSM·위험물·유해화학물질 여부를 확정하지 않습니다.")
    known = sum(profile.get(key) is not None for key in FLAG_FIELDS)
    if known == 0:
        warnings.append("작업·물질·설비 해당 여부를 아직 확인하지 않았습니다. 미확인은 비해당으로 처리하지 않습니다.")
    return list(dict.fromkeys(warnings))


def mark_updated(profile):
    result = normalize_profile(profile)
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result
