"""Korean EHS review workspace. User data lives only in the current browser session."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

st.set_page_config(page_title="EHS 법령 검토 도우미", page_icon="🏭", layout="wide")

from amendments import BASE_UNITS, BOOL_FIELDS, analyze_amendment
from core import build_checklist, checklist_dataframe, export_workbook
from profiles import (
    FLAG_FIELDS,
    NUMERIC_FIELDS,
    PROCESS_OPTIONS,
    TEMPLATE_OPTIONS,
    TEXT_FIELDS,
    get_template,
    normalize_profile,
    validate_profile,
)


APP_VERSION = "2.0.0"
WIDE = {"width": "stretch"} if tuple(int(part) for part in st.__version__.split(".")[:2]) >= (1, 50) else {"use_container_width": True}
TODAY = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
TRI_OPTIONS = ["미확인", "예", "아니오"]
DISPOSITION_OPTIONS = ["미착수", "자료 확인", "조치 중", "완료", "비대상 근거 확인"]
PUBLICATION_OPTIONS = ["현행 법령", "공포·시행 예정", "입법예고", "국회 법률안", "상태 미확인"]
BUILDING_COLUMNS = {
    "name": "건물명", "use": "건축물대장 용도", "structure": "구조",
    "gross_floor_area_m2": "연면적(m²)", "building_area_m2": "건축면적(m²)",
    "ground_floors": "지상층수", "basement_floors": "지하층수", "height_m": "높이(m)",
    "permit_status": "인허가 상태",
}
CHEMICAL_COLUMNS = {
    "name": "물질·제품명", "cas": "CAS 번호", "physical_state": "물리적 상태",
    "concentration_pct": "농도(%)", "max_storage_kg": "최대 저장량(kg)",
    "max_storage_l": "최대 저장량(L)", "daily_use_kg": "일 사용량(kg)",
    "annual_use_kg": "연 사용량(kg)", "hazard_classes": "법정 분류·유해성",
    "classification_verified": "분류 확인", "notes": "자료·메모",
}
EQUIPMENT_COLUMNS = {
    "kind": "설비 종류", "name": "설비명", "quantity": "수량", "rated_capacity": "정격·능력", "capacity_unit": "능력 단위",
    "inspection_status": "검사·인증 확인 상태", "location": "설치 위치",
}


def fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def review_fingerprint(profile: dict) -> str:
    return fingerprint({key: value for key, value in profile.items() if key not in ("uid", "id", "updated_at")})


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:80] or "사업장"


def safe_csv(dataframe: pd.DataFrame) -> bytes:
    def safe_cell(value):
        if isinstance(value, str) and re.match(r"^\s*[=+@-]", value):
            return "'" + value
        return value
    return dataframe.apply(lambda column: column.map(safe_cell)).to_csv(index=False).encode("utf-8-sig")


def nullable(value: object) -> object:
    if isinstance(value, list):
        return [nullable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): nullable(item) for key, item in value.items()}
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def tri_label(value: object) -> str:
    if value is True:
        return "예"
    if value is False:
        return "아니오"
    return "미확인"


def tri_value(label: str) -> bool | None:
    return {"예": True, "아니오": False}.get(label)


def access_gate() -> None:
    access_code = os.environ.get("EHS_ACCESS_CODE", "")
    if not access_code:
        try:
            access_code = str(st.secrets.get("access_code", ""))
        except (FileNotFoundError, KeyError):
            access_code = ""
        except Exception as exc:
            # A local application may deliberately have no secrets.toml.
            if exc.__class__.__name__ != "StreamlitSecretNotFoundError":
                raise
    if not access_code:
        return
    code_digest = hashlib.sha256(access_code.encode("utf-8")).hexdigest()
    if hmac.compare_digest(str(st.session_state.get("auth_digest", "")), code_digest):
        return
    st.title("EHS 법령 검토 도우미")
    st.caption("이 작업공간에는 접근 코드가 설정되어 있습니다.")
    with st.form("access_form"):
        entered = st.text_input("접근 코드", type="password")
        if st.form_submit_button("작업공간 열기", type="primary"):
            if hmac.compare_digest(entered, access_code):
                st.session_state["auth_digest"] = code_digest
                st.rerun()
            st.error("접근 코드가 일치하지 않습니다.")
    st.stop()


def initialize() -> None:
    if "sites" not in st.session_state:
        profile = normalize_profile(get_template(next(iter(TEMPLATE_OPTIONS))))
        uid = str(profile.get("uid") or uuid4().hex)
        profile["uid"] = uid
        st.session_state["sites"] = {uid: profile}
        st.session_state["site_selector"] = uid
    st.session_state.setdefault("revisions", {})
    st.session_state.setdefault("dispositions", {})
    st.session_state.setdefault("amendment_report", None)


def store_profile(profile: dict, uid: str) -> None:
    previous = st.session_state["sites"].get(uid)
    if previous is not None and review_fingerprint(previous) != review_fingerprint(profile):
        records = st.session_state["dispositions"].get(uid, {})
        for record in records.values():
            status = record.get("status")
            if status in ("완료", "비대상 근거 확인"):
                record["status"] = "자료 확인"
                record["memo"] = (str(record.get("memo") or "").rstrip() + f"\n[{TODAY} 제원 변경으로 재확인 필요 · 이전 상태: {status}]").strip()
    profile["uid"] = uid
    profile["updated_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    st.session_state["sites"][uid] = profile
    st.session_state["revisions"][uid] = st.session_state["revisions"].get(uid, 0) + 1
    st.session_state["amendment_report"] = None


def import_profiles(upload) -> None:
    if upload is None:
        st.warning("먼저 JSON 파일을 선택해 주세요.")
        return
    if upload.size > 5 * 1024 * 1024:
        st.error("프로필 파일은 5MB 이하로 선택해 주세요.")
        return
    try:
        data = json.loads(upload.getvalue().decode("utf-8-sig"))
        if isinstance(data, dict) and "profiles" in data:
            if data.get("format") != "ehs-profile-bundle" or data.get("version") != 1:
                raise ValueError("지원하는 형식은 이 앱에서 내보낸 버전 1 프로필 파일입니다.")
            items = data["profiles"]
        elif isinstance(data, dict) and "name" in data:
            items = [data]
        else:
            raise ValueError("사업장 프로필 구조를 확인해 주세요.")
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ValueError("사업장은 1~100개까지 불러올 수 있습니다.")
        staged = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("프로필 항목은 JSON 객체여야 합니다.")
            profile = normalize_profile(item)
            # Generate fresh identifiers so importing never overwrites an open site.
            uid = uuid4().hex
            profile["uid"] = uid
            staged.append((uid, profile, str(item.get("uid") or item.get("id") or "")))
        dispositions = data.get("dispositions", {}) if isinstance(data, dict) else {}
        for uid, profile, old_uid in staged:
            store_profile(profile, uid)
            if isinstance(dispositions, dict) and isinstance(dispositions.get(old_uid), dict):
                allowed = {}
                for rule_id, entry in dispositions[old_uid].items():
                    if isinstance(entry, dict):
                        allowed[str(rule_id)] = {
                            "status": entry.get("status") if entry.get("status") in DISPOSITION_OPTIONS else "미착수",
                            "owner": str(entry.get("owner", ""))[:200],
                            "due_date": str(entry.get("due_date", ""))[:20],
                            "memo": str(entry.get("memo", ""))[:20000],
                            "profile_revision_digest": str(entry.get("profile_revision_digest", "")),
                            "reviewed_on": str(entry.get("reviewed_on", "")),
                        }
                        record = allowed[str(rule_id)]
                        if record["status"] in ("완료", "비대상 근거 확인") and record["profile_revision_digest"] != review_fingerprint(profile):
                            previous_status = record["status"]
                            record["status"] = "자료 확인"
                            record["memo"] = (record["memo"].rstrip() + f"\n[{TODAY} 불러온 기록의 제원 기준 재확인 필요 · 이전 상태: {previous_status}]").strip()
                st.session_state["dispositions"][uid] = allowed
        st.session_state["next_site_selection"] = staged[0][0]
        st.session_state["flash"] = f"사업장 {len(staged)}개를 추가했습니다. 기존 프로필은 그대로 유지했습니다."
        st.rerun()
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        st.error(f"불러오지 못했습니다: {exc}")


def sidebar() -> str:
    sites = st.session_state["sites"]
    if "next_site_selection" in st.session_state:
        st.session_state["site_selector"] = st.session_state.pop("next_site_selection")
    if st.session_state.get("site_selector") not in sites:
        st.session_state["site_selector"] = next(iter(sites))
    with st.sidebar:
        st.markdown("### 🏭 사업장 작업공간")
        selected = st.selectbox(
            "분석할 사업장", list(sites), format_func=lambda uid: sites[uid].get("name") or "이름 미입력",
            key="site_selector",
        )
        st.caption(f"저장된 사업장 {len(sites)}개 · 현재 브라우저 세션")
        with st.expander("＋ 사업장 추가", expanded=False):
            with st.form("add_site_form"):
                template_id = st.selectbox("시작 공정·현장", list(TEMPLATE_OPTIONS), format_func=TEMPLATE_OPTIONS.get)
                name = st.text_input("새 사업장 이름", placeholder="예: A공장 / 신축공사 현장")
                if st.form_submit_button("새 프로필 만들기", **WIDE):
                    profile = normalize_profile(get_template(template_id))
                    profile["name"] = name.strip() or f"{TEMPLATE_OPTIONS[template_id]} {len(sites) + 1}"
                    uid = uuid4().hex
                    store_profile(profile, uid)
                    st.session_state["next_site_selection"] = uid
                    st.session_state["flash"] = "사업장을 추가했습니다. 템플릿의 공정은 출발점이며 제원은 직접 확인해 입력하세요."
                    st.rerun()
        with st.expander("프로필 저장·불러오기", expanded=False):
            bundle = {
                "format": "ehs-profile-bundle", "version": 1, "exported_on": TODAY,
                "profiles": list(sites.values()), "dispositions": st.session_state["dispositions"],
            }
            st.download_button(
                "전체 프로필 JSON 저장", json.dumps(bundle, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
                file_name=f"EHS_프로필_{TODAY}.json", mime="application/json", **WIDE,
            )
            upload = st.file_uploader("저장한 프로필 불러오기", type=["json"], key="profile_upload")
            if st.button("파일에서 사업장 추가", **WIDE):
                import_profiles(upload)
            st.caption("새로고침·세션 종료 시 입력이 사라질 수 있습니다. 작업 후 JSON을 저장하세요.")
        with st.expander("현재 사업장 삭제", expanded=False):
            confirm = st.checkbox("현재 사업장과 검토 기록을 삭제합니다.", key=f"delete_confirm_{selected}")
            if st.button("현재 사업장 삭제", disabled=not confirm or len(sites) <= 1, **WIDE):
                del sites[selected]
                st.session_state["dispositions"].pop(selected, None)
                st.session_state["revisions"].pop(selected, None)
                st.session_state["amendment_report"] = None
                st.session_state["next_site_selection"] = next(iter(sites))
                st.rerun()
            if len(sites) <= 1:
                st.caption("사업장은 최소 1개를 유지합니다.")
        st.divider()
        st.caption(f"v{APP_VERSION} · 한국 기준")
        st.caption("입력 → 해당성 검토 → 근거 확인 → 조치 기록")
        st.caption("법령 개정 자동 수집·자동 최신화는 포함되지 않습니다.")
    return selected


def numeric_widget(field: str, meta: dict, profile: dict, key: str):
    integer = meta.get("type") in ("int", "integer")
    value = profile.get(field)
    if value is not None:
        value = int(value) if integer else float(value)
    step = meta.get("step", 1 if integer else 1.0)
    return st.number_input(
        meta.get("label", field) + (f" ({meta['unit']})" if meta.get("unit") else ""), min_value=0 if integer else 0.0,
        value=value, step=int(step) if integer else float(step), key=key,
        placeholder="미확인", help=meta.get("help") or "미확인은 빈칸으로 두세요. 실제 0과 미확인은 다른 값입니다.",
    )


def text_widget(field: str, meta: dict, profile: dict, key: str):
    value = str(profile.get(field) or "")
    options = meta.get("options")
    if options:
        options = list(options)
        if value and value not in options:
            options.append(value)
        return st.selectbox(meta.get("label", field), options, index=options.index(value) if value in options else 0, key=key)
    if field == "profile_notes" or meta.get("type") == "textarea":
        return st.text_area(meta.get("label", field), value=value, key=key, height=100)
    return st.text_input(meta.get("label", field), value=value, key=key, help=meta.get("help"))


def inventory_editor(profile: dict, field: str, columns: dict, key: str, numeric: list[str]) -> list[dict]:
    records = copy.deepcopy(profile.get(field) or [])
    for row in records:
        for name in columns:
            row.setdefault(name, None)
        if field == "chemicals":
            if isinstance(row.get("hazard_classes"), list):
                row["hazard_classes"] = ", ".join(row["hazard_classes"])
            row["classification_verified"] = tri_label(row.get("classification_verified"))
    data = pd.DataFrame(records, columns=list(columns))
    configs = {name: st.column_config.TextColumn(label) for name, label in columns.items()}
    for name in numeric:
        data[name] = pd.to_numeric(data[name], errors="coerce").astype("float64")
        integer_column = name in ("ground_floors", "basement_floors", "quantity")
        configs[name] = st.column_config.NumberColumn(columns[name], min_value=0.0, step=1.0 if integer_column else None, format="%d" if integer_column else None)
    if field == "chemicals":
        configs["classification_verified"] = st.column_config.SelectboxColumn("분류 확인", options=TRI_OPTIONS)
        configs["physical_state"] = st.column_config.SelectboxColumn("물리적 상태", options=["미확인", "고체", "액체", "기체"])
    edited = st.data_editor(data, num_rows="dynamic", hide_index=True, **WIDE, column_config=configs, key=key)
    result = []
    for record in edited.to_dict("records"):
        record = nullable(record)
        if field == "chemicals":
            record["classification_verified"] = tri_value(record.get("classification_verified", "미확인"))
        if any(value not in (None, "", "미확인") for name, value in record.items() if name != "classification_verified"):
            result.append(record)
    return result


def profile_tab(uid: str, profile: dict) -> None:
    st.subheader("사업장 제원과 작업 조건")
    st.caption("건축물대장·설비명세·물질목록·인원현황 등 확인한 자료를 입력하세요. 빈 숫자와 ‘미확인’은 추가 확인 항목으로 남습니다.")
    if profile.get("template_is_example"):
        st.info("공정 템플릿에서 시작한 프로필입니다. 템플릿은 실제 회사의 제원을 의미하지 않으며 인원·규모·위험 여부는 직접 확인해 입력해야 합니다.")
    warnings = validate_profile(profile)
    if warnings:
        with st.expander(f"입력·자료 추가 확인 {len(warnings)}건", expanded=False):
            for warning in warnings:
                st.write(f"• {warning}")
    revision = st.session_state["revisions"].get(uid, 0)
    prefix = f"profile_{uid}_{revision}"
    with st.form(f"{prefix}_form"):
        proposed = copy.deepcopy(profile)
        basecols = st.columns(3)
        text_fields = [(key, meta) for key, meta in TEXT_FIELDS.items() if key != "profile_notes"]
        for index, (field, meta) in enumerate(text_fields):
            with basecols[index % 3]:
                proposed[field] = text_widget(field, meta, profile, f"{prefix}_{field}")
        proposed["processes"] = st.multiselect(
            "공정·작업 선택 (복수 선택)", list(PROCESS_OPTIONS),
            default=[item for item in profile.get("processes", []) if item in PROCESS_OPTIONS],
            format_func=PROCESS_OPTIONS.get, key=f"{prefix}_processes",
            help="공장 전체 업종과 별도로 실제 공정을 선택합니다. 건설현장도 작업별로 복수 선택할 수 있습니다.",
        )
        groups = []
        for schema in (NUMERIC_FIELDS, FLAG_FIELDS):
            for meta in schema.values():
                group = meta.get("group", "기타 제원")
                if group not in groups:
                    groups.append(group)
        for group in groups:
            with st.expander(group, expanded=group == groups[0]):
                cols = st.columns(3)
                fields = [(field, meta, "number") for field, meta in NUMERIC_FIELDS.items() if meta.get("group", "기타 제원") == group]
                fields += [(field, meta, "flag") for field, meta in FLAG_FIELDS.items() if meta.get("group", "기타 제원") == group]
                for index, (field, meta, kind) in enumerate(fields):
                    with cols[index % 3]:
                        if kind == "number":
                            proposed[field] = numeric_widget(field, meta, profile, f"{prefix}_{field}")
                        else:
                            label = tri_label(profile.get(field))
                            proposed[field] = tri_value(st.selectbox(
                                meta.get("label", field), TRI_OPTIONS, index=TRI_OPTIONS.index(label),
                                key=f"{prefix}_{field}", help=meta.get("help"),
                            ))
        with st.expander("건물별 세부 명세", expanded=False):
            st.caption("여러 동을 한 면적으로 합산하면 일부 적용 기준을 판단할 수 없습니다. 용도와 층수는 건물별로 작성하세요.")
            proposed["buildings"] = inventory_editor(profile, "buildings", BUILDING_COLUMNS, f"{prefix}_buildings", ["gross_floor_area_m2", "building_area_m2", "ground_floors", "basement_floors", "height_m"])
        with st.expander("화학물질·혼합제품 목록", expanded=False):
            st.caption("MSDS와 법정 분류를 확인해 입력하세요. kg와 L는 환산하지 않습니다. 물질명만으로 유해화학물질·위험물·PSM 대상을 확정하지 않습니다.")
            proposed["chemicals"] = inventory_editor(profile, "chemicals", CHEMICAL_COLUMNS, f"{prefix}_chemicals", ["concentration_pct", "max_storage_kg", "max_storage_l", "daily_use_kg", "annual_use_kg"])
        with st.expander("기계·설비 목록", expanded=False):
            st.caption("프레스·전단기·크레인·리프트·압력용기·산업용 로봇 등을 구분하고 정격능력과 단위를 함께 적으세요.")
            proposed["equipment"] = inventory_editor(profile, "equipment", EQUIPMENT_COLUMNS, f"{prefix}_equipment", ["quantity", "rated_capacity"])
        if "profile_notes" in TEXT_FIELDS:
            proposed["profile_notes"] = text_widget("profile_notes", TEXT_FIELDS["profile_notes"], profile, f"{prefix}_notes")
        submitted = st.form_submit_button("제원 저장하고 검토에 반영", type="primary", **WIDE)
        if submitted:
            errors = []
            if not str(proposed.get("name", "")).strip():
                errors.append("사업장 이름을 입력해 주세요.")
            for chemical in proposed.get("chemicals", []):
                concentration = chemical.get("concentration_pct")
                if concentration is not None and concentration > 100:
                    errors.append("화학물질 농도는 0~100% 범위로 입력해 주세요.")
            for table, integer_columns in (("buildings", ["ground_floors", "basement_floors"]), ("equipment", ["quantity"])):
                for record in proposed.get(table, []):
                    for field in integer_columns:
                        value = record.get(field)
                        if value is not None and not float(value).is_integer():
                            errors.append("층수와 설비 수량은 정수로 입력해 주세요.")
            if errors:
                for error in errors:
                    st.error(error)
            else:
                proposed = normalize_profile(proposed)
                store_profile(proposed, uid)
                st.session_state["flash"] = "사업장 제원을 저장했습니다. 이전 완료·비대상 검토 기록은 제원이 바뀌면 ‘자료 확인’으로 전환합니다. 개정 분석은 다시 실행해야 합니다."
                st.rerun()


def detail_list(label: str, values: list | None) -> None:
    if values:
        st.markdown(f"**{label}**")
        for item in values:
            if isinstance(item, dict):
                description = f"{item.get('label') or item.get('field') or '기준'} {item.get('operator', '')} {item.get('value', '')}{item.get('unit', '')}"
                if item.get("before") is not None:
                    description += f" · 개정 전 {item['before']}{item.get('unit', '')}"
                if item.get("source_text"):
                    description += f" · 원문: {item['source_text']}"
                st.markdown(f"- {description}")
            else:
                st.markdown(f"- {item}")


def checklist_tab(uid: str, profile: dict, rows: list[dict]) -> None:
    st.subheader("해당성에 따라 준비하는 체크리스트")
    st.caption("검토대상은 의무 확정·준수 완료를 뜻하지 않습니다. 각 항목에서 조문, 적용 범위, 추가 자료와 실무 조치를 함께 확인하세요.")
    cols = st.columns(3)
    for col, value in zip(cols, ["검토대상", "추가확인", "현재정보상비대상"]):
        col.metric({"검토대상": "검토 대상", "추가확인": "추가 확인", "현재정보상비대상": "현재 정보상 비대상"}[value], sum(row.get("applicability") == value for row in rows))
    filters = st.columns([2, 2, 3])
    categories = sorted({row.get("category", "기타") for row in rows})
    selected_categories = filters[0].multiselect("분류", categories, default=categories, key=f"cats_{uid}")
    selected_status = filters[1].multiselect("해당성", ["검토대상", "추가확인", "현재정보상비대상"], default=["검토대상", "추가확인"], key=f"status_{uid}")
    query = filters[2].text_input("항목·법령 검색", key=f"search_{uid}")
    filtered = [row for row in rows if row.get("category") in selected_categories and row.get("applicability") in selected_status and query.strip().lower() in " ".join(str(row.get(field, "")) for field in ("title", "law_name", "article", "scope_note")).lower()]
    dispositions = st.session_state["dispositions"].setdefault(uid, {})
    if filtered:
        st.dataframe(checklist_dataframe(filtered, dispositions), hide_index=True, **WIDE)
        selected_id = st.selectbox(
            "상세 확인할 항목", [row["rule_id"] for row in filtered],
            format_func=lambda rule_id: next(f"{row['title']} · {row['applicability']}" for row in filtered if row["rule_id"] == rule_id),
            key=f"detail_rule_{uid}",
        )
        row = next(row for row in filtered if row["rule_id"] == selected_id)
        with st.container(border=True):
            st.markdown(f"#### {row['title']}")
            st.caption(f"{row.get('rule_kind', '검토 항목')} · {row.get('law_name', '')} {row.get('article', '')}")
            st.write(row.get("scope_note", ""))
            if row.get("source_url"):
                st.link_button("법령·공식 근거 열기", row["source_url"])
            st.caption(f"근거 확인일: {row.get('source_checked_on') or '확인 필요'}")
            left, right = st.columns(2)
            with left:
                detail_list("확인·실행할 사항", row.get("actions"))
                detail_list("준비할 증빙", row.get("evidence"))
            with right:
                detail_list("판단에 사용한 입력", row.get("matched_fields"))
                detail_list("추가로 필요한 입력", row.get("missing_fields"))
            previous = dispositions.get(selected_id, {})
            if previous and previous.get("profile_revision_digest") != review_fingerprint(profile):
                st.warning("이 기록은 이전 제원 또는 기준이 확인되지 않은 제원에서 작성했습니다. 현재 조건으로 다시 확인하고 저장하세요.")
            with st.form(f"disposition_{uid}_{selected_id}"):
                col1, col2, col3 = st.columns(3)
                status = col1.selectbox("조치 상태", DISPOSITION_OPTIONS, index=DISPOSITION_OPTIONS.index(previous.get("status", "미착수")) if previous.get("status") in DISPOSITION_OPTIONS else 0)
                owner = col2.text_input("담당자·부서", value=previous.get("owner", ""))
                due = col3.text_input("확인·조치 기한", value=previous.get("due_date", ""), placeholder="YYYY-MM-DD / 미정은 빈칸")
                memo = st.text_area("검토 근거·조치 내용", value=previous.get("memo", ""), height=90)
                if st.form_submit_button("이 항목의 검토 기록 저장"):
                    if due and not valid_iso_date(due):
                        st.error("기한은 YYYY-MM-DD 형식으로 적거나 빈칸으로 두세요.")
                    else:
                        dispositions[selected_id] = {"status": status, "owner": owner, "due_date": due, "memo": memo, "profile_revision_digest": review_fingerprint(profile), "reviewed_on": TODAY}
                        st.session_state["flash"] = "검토 기록을 저장했습니다. 이 상태는 담당자의 기록이며 자동 준수 판정은 아닙니다."
                        st.rerun()
    else:
        st.info("필터에 맞는 항목이 없습니다. 분류 또는 해당성을 더 선택하세요.")
    st.divider()
    st.caption("파일에는 필터와 관계없이 전체 항목을 포함합니다. ‘비대상’ 항목도 근거를 확인할 수 있도록 남깁니다.")
    csv = safe_csv(checklist_dataframe(rows, dispositions))
    impact_report = current_report_for(uid, profile)
    excel = export_workbook(profile, rows, impact=impact_report, dispositions=dispositions)
    buttons = st.columns(2)
    buttons[0].download_button("체크리스트 Excel 저장", data=excel, file_name=f"{safe_filename(profile.get('name', '사업장'))}_EHS_{TODAY}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", **WIDE, key=f"excel_{uid}")
    buttons[1].download_button("체크리스트 CSV 저장", data=csv, file_name=f"{safe_filename(profile.get('name', '사업장'))}_체크리스트.csv", mime="text/csv", **WIDE, key=f"csv_{uid}")


def valid_iso_date(value: str) -> bool:
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and datetime.strptime(value, "%Y-%m-%d").date().isoformat() == value
    except ValueError:
        return False


def current_report_for(uid: str, profile: dict) -> dict | None:
    report = st.session_state.get("amendment_report")
    if not report or report.get("digests", {}).get(uid) != fingerprint(profile):
        return None
    return report.get("results", {}).get(uid)


def amendment_form() -> tuple[dict, str, bool]:
    with st.form("amendment_form"):
        cols = st.columns(2)
        title = cols[0].text_input("법령·개정 문서명", placeholder="예: ○○법 시행규칙 일부개정령안")
        law_family = cols[1].selectbox("관련 법령 분야", ["전체", "산업안전보건", "건축", "건설", "소방", "위험물", "화학물질", "가스", "환경", "기타"])
        dates = st.columns(3)
        publication_status = dates[0].selectbox("문서의 법적 상태", PUBLICATION_OPTIONS, index=4)
        published_on = dates[1].text_input("공포일·공개일", placeholder="YYYY-MM-DD / 미확인은 빈칸")
        effective_on = dates[2].text_input("시행일", placeholder="YYYY-MM-DD / 미확인은 빈칸")
        source_url = st.text_input("공식 문서 URL", placeholder="https://www.law.go.kr/… / 공식 입법예고·공포 자료")
        text = st.text_area("개정 조문·이유·적용례 원문", height=240, placeholder="개정 대상, 적용 대상, 시행일과 부칙·경과조치를 포함한 원문을 붙여 넣으세요. 신구조문 대비표를 함께 입력하면 확인에 도움이 됩니다.")
        scope = st.radio("비교할 사업장", ["현재 선택한 사업장", "저장된 전체 사업장"], horizontal=True)
        with st.expander("수치·범위 개정 조건을 직접 지정", expanded=False):
            st.caption("원문에서 확인한 변경만 입력하세요. 빈 행은 분석에 사용하지 않습니다. 수치나 시행일을 입력하면 해당 문구를 원문에도 남겨 근거를 대조하세요.")
            column_names = ["topic", "field", "operator", "before", "after", "unit", "effective_on", "source_excerpt"]
            data = pd.DataFrame(columns=column_names)
            field_labels = {key: value.get("label", key) for key, value in NUMERIC_FIELDS.items() if key in BASE_UNITS}
            field_labels.update({key: value.get("label", key) for key, value in FLAG_FIELDS.items() if key in BOOL_FIELDS})
            changes_df = st.data_editor(
                data, num_rows="dynamic", hide_index=True, **WIDE, key="amendment_changes",
                column_config={
                    "topic": st.column_config.TextColumn("개정 주제"),
                    "field": st.column_config.SelectboxColumn("비교할 제원", options=list(field_labels.values()), help="사업장 입력 항목 중 실제 개정 조건에 사용되는 제원을 선택하세요."),
                    "operator": st.column_config.SelectboxColumn("조건", options=[">=", ">", "<=", "<", "=="]),
                    "before": st.column_config.TextColumn("개정 전 기준 값", help="수치는 숫자로, 여부 조건은 예 또는 아니오로 입력합니다."),
                    "after": st.column_config.TextColumn("개정 후 기준 값", help="수치 비교에는 단위도 입력하세요. 여부 비교는 예/아니오와 == 조건을 사용합니다."),
                    "unit": st.column_config.TextColumn("단위"),
                    "effective_on": st.column_config.TextColumn("개별 시행일(YYYY-MM-DD)"),
                    "source_excerpt": st.column_config.TextColumn("근거가 되는 원문 문구"),
                },
            )
            st.caption("비교 가능한 입력 항목과 기준 단위")
            st.dataframe(pd.DataFrame([{"입력 항목": label, "기준 단위": BASE_UNITS.get(key, "예/아니오")} for key, label in field_labels.items()]), hide_index=True, **WIDE, height=160)
        submitted = st.form_submit_button("입력 문서와 사업장 비교", type="primary", **WIDE)
    changes = [nullable(row) for row in changes_df.to_dict("records") if row.get("field") not in (None, "") and not pd.isna(row.get("field"))]
    label_to_key = {label: key for key, label in field_labels.items()}
    for change in changes:
        change["field"] = label_to_key.get(change.get("field"), change.get("field"))
        if change.get("field") in BOOL_FIELDS:
            for side in ("before", "after"):
                if change.get(side) in ("예", "아니오"):
                    change[side] = tri_value(change[side])
    doc = {"title": title, "law_family": law_family, "text": text, "publication_status": publication_status, "published_on": published_on, "effective_on": effective_on, "source_url": source_url, "analysis_date": TODAY, "changes": changes}
    return doc, scope, submitted


def amendment_result(result: dict) -> None:
    st.markdown(f"**{result.get('status', '검토 결과')}**")
    st.write(result.get("summary", ""))
    for warning in result.get("warnings", []):
        st.warning(warning)
    dates = result.get("extracted_dates", [])
    if dates:
        date_labels = [f"{item.get('date', '')} ({item.get('kind', '원문')})" if isinstance(item, dict) else str(item) for item in dates]
        st.caption(f"원문에서 확인된 날짜 표현: {', '.join(date_labels)}")
    results = result.get("results", [])
    if not results:
        st.info("비교할 수 있는 적용 대상이 충분히 확인되지 않았습니다. 원문과 적용례를 더 입력해 주세요.")
    for item in results:
        with st.expander(f"{item.get('applicability', '추가 확인')} · {item.get('title', '검토 항목')}"):
            if item.get("quote"):
                st.markdown("**관련 원문**")
                st.write(item["quote"])
            if item.get("matched_terms"):
                st.caption("관련 표현: " + ", ".join(item["matched_terms"]))
            detail_list("사업장 입력 근거", item.get("profile_evidence"))
            st.markdown("**시행·적용 시점**")
            st.write(item.get("timing", "추가 확인"))
            detail_list("수치·범위 변경 검토", item.get("thresholds"))
            detail_list("추가로 필요한 입력", item.get("missing_fields"))
            detail_list("확인·대응할 사항", item.get("actions"))


def amendment_tab(uid: str, profile: dict) -> None:
    st.subheader("개정 문서 영향성 평가")
    st.caption("공식 원문을 넣어 사업장 제원과 관련 표현·변경 조건을 비교합니다. 시행 중인 법령, 시행 예정 개정, 입법예고와 법률안을 구분하며 원문에 없는 의무나 기한을 생성하지 않습니다.")
    doc, scope, submitted = amendment_form()
    if submitted:
        errors = []
        if not doc["text"].strip():
            errors.append("비교할 원문을 입력해 주세요.")
        if len(doc["text"]) > 400000:
            errors.append("원문은 40만 자 이하로 나누어 입력해 주세요.")
        for field, label in [("published_on", "공포일·공개일"), ("effective_on", "시행일")]:
            if doc[field] and not valid_iso_date(doc[field]):
                errors.append(f"{label}은 YYYY-MM-DD 형식으로 적거나 빈칸으로 두세요.")
        if doc["source_url"] and not re.match(r"^https?://[^\s]+$", doc["source_url"]):
            errors.append("출처는 http 또는 https URL로 입력해 주세요.")
        for error in errors:
            st.error(error)
        if not errors:
            selected_sites = st.session_state["sites"] if scope == "저장된 전체 사업장" else {uid: profile}
            results = {site_id: analyze_amendment(site, doc) for site_id, site in selected_sites.items()}
            st.session_state["amendment_report"] = {"doc": doc, "results": results, "digests": {site_id: fingerprint(site) for site_id, site in selected_sites.items()}, "created_on": TODAY}
    report = st.session_state.get("amendment_report")
    if report:
        valid_results = {site_id: result for site_id, result in report["results"].items() if site_id in st.session_state["sites"] and report["digests"].get(site_id) == fingerprint(st.session_state["sites"][site_id])}
        if not valid_results:
            st.info("프로필이 바뀌었습니다. 새 제원으로 다시 비교해 주세요.")
            return
        st.divider()
        st.caption("아래는 마지막으로 분석한 문서의 결과입니다. 위 입력을 바꾼 경우 다시 비교 버튼을 누르세요.")
        st.caption(f"분석 문서: {report['doc'].get('title') or '제목 미입력'} · 문서 상태: {report['doc']['publication_status']} · 분석 기준일: {report['created_on']}")
        if len(valid_results) > 1:
            st.dataframe(pd.DataFrame([{"사업장": st.session_state["sites"][site_id]["name"], "종합 상태": result.get("status", "추가 확인"), "검토 항목": len(result.get("results", [])), "관련성 확인": sum(item.get("applicability") == "관련성 확인" for item in result.get("results", [])), "추가 확인": sum(item.get("applicability") == "추가 확인" for item in result.get("results", []))} for site_id, result in valid_results.items()]), hide_index=True, **WIDE)
        site_names = {site_id: st.session_state["sites"][site_id]["name"] for site_id in valid_results}
        selected_result = st.selectbox("분석 결과를 볼 사업장", list(valid_results), index=list(valid_results).index(uid) if uid in valid_results else 0, format_func=site_names.get, key="amendment_result_site")
        amendment_result(valid_results[selected_result])
        st.download_button("개정 검토 결과 JSON 저장", json.dumps(report, ensure_ascii=False, indent=2, default=str).encode("utf-8"), file_name=f"개정검토_{TODAY}.json", mime="application/json", key="impact_json")
        target = st.session_state["sites"][selected_result]
        st.download_button("개정 검토 포함 Excel 저장", export_workbook(target, build_checklist(target), impact=valid_results[selected_result], dispositions=st.session_state["dispositions"].get(selected_result, {})), file_name=f"{safe_filename(target['name'])}_개정검토_{TODAY}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="impact_excel")


def reference_tab(rows: list[dict]) -> None:
    st.subheader("근거와 판단 범위")
    st.markdown("이 도구는 사업장 제원을 바탕으로 **먼저 확인할 항목과 증빙을 정리하는 검토 도구**입니다. 업종·규모·물질·설비별 상세 요건, 인허가 이력, 지방자치단체 조례와 경과조치는 해당 원문과 관할기관 자료를 확인해야 합니다.")
    st.markdown("- **검토대상:** 입력 조건이 항목과 연결돼 근거 검토가 필요합니다.\n- **추가확인:** 판단에 필요한 제원·분류·범위가 확인되지 않았습니다.\n- **현재정보상비대상:** 입력한 조건으로는 연결되지 않습니다. 입력 누락·오류와 다른 조문까지 배제하지 않습니다.\n- **조치 상태:** 담당자가 남기는 진행 기록이며 법적 준수 인증이 아닙니다.")
    source_records = {}
    for row in rows:
        key = (row.get("law_name", ""), row.get("source_url", ""), row.get("source_checked_on", ""))
        source_records[key] = {"법령·공식 자료": key[0], "출처 URL": key[1], "근거 확인일": key[2] or "확인 필요"}
    st.dataframe(pd.DataFrame(source_records.values()), hide_index=True, **WIDE, column_config={"출처 URL": st.column_config.LinkColumn("공식 근거")})
    st.info("근거 확인일 이후의 개정은 자동으로 수집되지 않습니다. 새 문서는 ‘개정 영향성’에서 비교하고, 법령·적용례 확인 결과를 체크리스트의 검토 기록에 남기세요.")
    st.markdown("**권장 작업 순서**\n\n1. 공정 템플릿으로 사업장을 추가하고 자료에 근거해 제원을 입력합니다.\n2. 추가 확인 항목에 필요한 인원·건물·물질·설비 자료를 보완합니다.\n3. 검토 대상의 공식 근거와 예외·경과조치를 확인한 뒤 담당자와 기한을 기록합니다.\n4. 새 개정 문서를 비교해 대응 항목을 정리합니다.\n5. Excel 결과와 전체 프로필 JSON을 저장합니다.")


def main() -> None:
    access_gate()
    initialize()
    st.markdown("""<style>
    .block-container{padding-top:2rem;padding-bottom:3rem;max-width:1600px;}
    [data-testid='stMetric']{border:1px solid #e3e8ef;border-radius:12px;padding:16px;background:#f8fafc;}
    [data-testid='stSidebar']{background:#f4f7fb;}
    h1{letter-spacing:-.045em;} .stTabs [data-baseweb='tab']{font-weight:600;}
    </style>""", unsafe_allow_html=True)
    uid = sidebar()
    profile = st.session_state["sites"][uid]
    st.title("EHS 법령 검토 도우미")
    st.write("제조공정부터 신축·건설현장까지, 사업장 조건에 맞는 법령 확인과 조치를 한곳에서 정리합니다.")
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))
    st.caption(f"현재 사업장: {profile.get('name') or '이름 미입력'} · 공정 {len(profile.get('processes', []))}개 · 확인하지 않은 값은 빈칸으로 유지")
    rows = build_checklist(profile)
    tab1, tab2, tab3, tab4 = st.tabs(["① 사업장 제원", "② 체크리스트", "③ 개정 영향성", "근거·사용 안내"])
    with tab1:
        profile_tab(uid, profile)
    with tab2:
        checklist_tab(uid, profile, rows)
    with tab3:
        amendment_tab(uid, profile)
    with tab4:
        reference_tab(rows)


if __name__ == "__main__":
    main()
