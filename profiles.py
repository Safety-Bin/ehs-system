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
               "template_is_example": False, "updated_at": ""}
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


def normalize_profile(data):
    if not isinstance(data, dict):
        raise ValueError("사업장 프로필은 객체 형태여야 합니다.")
    profile = empty_profile(str(data.get("name") or "이름 없는 사업장"))
    for key in ("uid", "template_id", "updated_at"):
        if data.get(key):
            profile[key] = str(data[key])
    profile["template_is_example"] = _flag(data.get("template_is_example")) is True
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
