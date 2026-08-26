import streamlit as st
import pandas as pd
import io

# ==========================================
# [보안 로직] 패스워드 인증 창 (이 부분을 새로 추가!)
# ==========================================
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

if not st.session_state['authenticated']:
    st.title("🔒 초격차 EHS 시스템 접근 제어")
    st.info("인가된 관리자만 접근할 수 있습니다. 접근 코드(Access Code)를 입력하세요.")
    
    pwd = st.text_input("Access Code", type="password") # 비밀번호 칠 때 까만 점(***)으로 나옴
    
    if st.button("접속 (Login)"):
        if pwd == "hynix2026":  # 원하는 비밀번호로 수정 가능 (예: hynix2026)
            st.session_state['authenticated'] = True
            st.rerun() # 인증 성공 시 앱 새로고침
        else:
            st.error("🚨 접근 코드가 일치하지 않습니다.")
    
    st.stop() # 인증을 통과하지 못하면 이 아래 코드(본문)는 절대 실행되지 않음!

# ==========================================
import streamlit as st
import pandas as pd
import io

# ==========================================
# 0. 앱 기본 설정 및 다중 프로필 DB (Session State)
# ==========================================
st.set_page_config(page_title="EHS 자동화 시스템", layout="wide")

# 세션 상태(Session State)를 이용해 여러 공장의 프로필을 메모리에 저장
if 'factory_db' not in st.session_state:
    st.session_state['factory_db'] = {
        "1공장 (반도체 메인 FAB)": {
            "area": 55000, "floors": 4, "cleanroom": True,
            "psm_target": True, "chem_types": ["불산", "황산", "과산화수소"],
            "danger_multiple": 5000, "explosion_proof": True, "confined_space": True
        },
        "2공장 (유틸리티 및 폐수처리장)": {
            "area": 8000, "floors": 2, "cleanroom": False,
            "psm_target": False, "chem_types": ["수산화나트륨"],
            "danger_multiple": 50, "explosion_proof": False, "confined_space": True
        }
    }

st.title("🏭 EHS 인허가 및 법규 영향성 자동화 시스템")
st.markdown("다중 사업장(Multi-Site)의 상세 설비/화학물질 프로필을 관리하고, 맞춤형 법규 체크리스트 및 개정안 영향성을 분석합니다.")

# ==========================================
# 1. 사이드바: 사업장 선택 및 관리
# ==========================================
st.sidebar.header("🏢 사업장 프로필 관리")
factory_names = list(st.session_state['factory_db'].keys())
selected_factory = st.sidebar.selectbox("📂 분석할 사업장(공장) 선택", factory_names)

# 선택된 공장의 현재 데이터 불러오기
cur_data = st.session_state['factory_db'][selected_factory]

st.sidebar.markdown("---")
st.sidebar.info("💡시연용 프로토타입입니다. 실제 도입 시 사내 ERP/화학물질 관리 시스템과 API로 연동됩니다.")

# ==========================================
# 2. 메인 화면 3개의 탭(Tab) 구성
# ==========================================
tab1, tab2, tab3 = st.tabs(["⚙️ 상세 프로필 설정 (PSM/소방)", "📋 맞춤형 법규 체크리스트 추출", "🚨 신규 법안 영향성 평가 (AI 시뮬)"])

# ------------------------------------------
# [Tab 1] 15년 차 베테랑의 디테일한 공장 프로필 설정
# ------------------------------------------
with tab1:
    st.subheader(f"🛠️ [{selected_factory}] EHS 상세 제원 설정")
    
    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 🏗️ 건축 및 기본 제원")
            new_area = st.number_input("연면적 (m²)", min_value=0, value=cur_data["area"], step=500)
            new_floors = st.number_input("층수", min_value=1, value=cur_data["floors"])
            new_cleanroom = st.checkbox("반도체 클린룸(Clean Room) 유무", value=cur_data["cleanroom"])
            new_confined = st.checkbox("밀폐공간(폐수조, 맨홀 등) 보유 여부", value=cur_data["confined_space"])
            
        with col2:
            st.markdown("#### 🧪 공정안전(PSM) 및 위험물 제원")
            new_psm = st.checkbox("PSM(공정안전보고서) 제출 대상 사업장", value=cur_data["psm_target"])
            new_danger = st.number_input("위험물 지정수량 배수 (총합)", min_value=0, value=cur_data["danger_multiple"], help="예: 3000배 이상 시 자체소방대 편성 대상")
            new_exp = st.checkbox("방폭구역(Zone 0, 1, 2) 설정 여부", value=cur_data["explosion_proof"])
            
            # 화학물질 다중 선택
            chem_options = ["황산", "불산", "과산화수소", "수산화나트륨", "질산", "실란(Silane)"]
            new_chems = st.multiselect("주요 취급 유해화학물질", chem_options, default=cur_data["chem_types"])
            
        submitted = st.form_submit_button("💾 프로필 저장/업데이트")
        if submitted:
            # 세션 스테이트 업데이트
            st.session_state['factory_db'][selected_factory] = {
                "area": new_area, "floors": new_floors, "cleanroom": new_cleanroom,
                "confined_space": new_confined, "psm_target": new_psm, 
                "danger_multiple": new_danger, "explosion_proof": new_exp, "chem_types": new_chems
            }
            st.success(f"{selected_factory}의 EHS 프로필이 성공적으로 업데이트되었습니다! (상단 탭을 이동해 확인하세요)")

# 새로 업데이트된 데이터로 변수 재할당 (Tab 2, 3용)
cur_data = st.session_state['factory_db'][selected_factory]

# ------------------------------------------
# [Tab 2] 상세 프로필 기반 체크리스트 추출
# ------------------------------------------
with tab2:
    st.subheader(f"📊 [{selected_factory}] 타겟팅 법무 체크리스트")
    rules = []
    
    # 1. 소방(NFPC) / 건축법 로직
    if cur_data["area"] >= 3000:
        rules.append({"분류": "소방(일반)", "점검 항목": "자동화재탐지설비 및 시각경보기 연동 상태 점검", "근거 법령": "NFPC 203"})
    if cur_data["danger_multiple"] >= 3000:
        rules.append({"분류": "소방(위험물)", "점검 항목": "자체소방대 편성 및 화학차/포소화설비 확보 여부", "근거 법령": "위험물안전관리법 제18조"})
    
    # 2. 산안법 / PSM 로직
    if cur_data["psm_target"]:
        rules.append({"분류": "안전(PSM)", "점검 항목": "12대 실천과제(안전작업허가, 변경요소관리 등) 이행 여부", "근거 법령": "산안법 제44조"})
    if cur_data["explosion_proof"]:
        rules.append({"분류": "안전(방폭)", "점검 항목": "방폭기기(Ex) 방폭 등급 유지 및 케이블 글랜드 체결 상태", "근거 법령": "산업안전보건기준에관한규칙 제311조"})
    if "실란(Silane)" in cur_data["chem_types"] or "불산" in cur_data["chem_types"]:
        rules.append({"분류": "안전(독성/가스)", "점검 항목": "가스누출감지경보기 및 국소배기장치 인터록(Interlock) 연동", "근거 법령": "KOSHA Guide P-135"})
    if cur_data["cleanroom"]:
        rules.append({"분류": "소방(특수)", "점검 항목": "클린룸 하부 Access Floor 내 연기감지기(ASD) 설치 및 작동", "근거 법령": "NFPC 101"})

    if len(rules) > 0:
        df = pd.DataFrame(rules)
        st.dataframe(df, use_container_width=True)
        
        def to_excel(df):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Checklist')
            return output.getvalue()
            
        st.download_button("📥 맞춤형 실무 엑셀 다운로드", data=to_excel(df), file_name=f'{selected_factory}_Checklist.xlsx')

# ------------------------------------------
# [Tab 3] 신규 법안 영향성 평가 (AI 시뮬레이션)
# ------------------------------------------
with tab3:
    st.subheader(f"🔎 [{selected_factory}] 개정 법안 영향성 평가 (Impact Assessment)")
    st.markdown("입력된 신규 법안이 현재 선택된 사업장의 **PSM, 위험물, 취급 화학물질 DB**와 충돌하는지 교차 검증합니다.")
    
    new_law_text = st.text_area("신규 제·개정 법안 텍스트 붙여넣기", height=150, 
                                placeholder="예시: 불산 취급 공정 내 방폭설비 정기 점검 주기 단축 및 밀폐공간 작업 시 스마트 환기장치 의무화 고시...")
    
    if st.button("🚀 교차 검증 및 영향성 분석 실행"):
        if not new_law_text:
            st.warning("법안 텍스트를 입력해주세요.")
        else:
            st.markdown("---")
            st.markdown("### 📑 AI 분석 결과 리포트")
            
            # 위험물/방폭 + 화학물질 복합 시나리오
            if "불산" in new_law_text and "불산" in cur_data["chem_types"] and cur_data["explosion_proof"]:
                st.error("🚨 **[영향성: 치명(High)] 1공장(FAB) 핵심 공정 직접 규제 대상입니다!**")
                st.markdown(f"""
                * **트리거(Trigger):** 불산 취급 + 방폭설비 보유
                * **현재 당사 상태:** {selected_factory}는 불산을 취급하며 방폭구역이 설정되어 있습니다.
                * **📌 EHS 실무 Action Plan:** 
                    1. 공무팀 협조: 해당 구역 방폭 기기(센서, 모터) 리스트 추출 및 점검 주기 단축(1년->6개월)안 기안
                    2. 변경요소관리(MOC) 절차서 업데이트
                """)
            
            elif "밀폐공간" in new_law_text and cur_data["confined_space"]:
                st.warning("⚠️ **[영향성: 주의(Medium)] 절차서(SOP) 개정 검토 필요**")
                st.markdown(f"""
                * **트리거(Trigger):** 밀폐공간 작업 절차
                * **현재 당사 상태:** {selected_factory} 내 폐수조 등 밀폐공간 보유.
                * **📌 EHS 실무 Action Plan:** PTW(작업허가서) 양식에 '스마트 환기장치' 체크 항목 추가.
                """)
                
            else:
                st.success("✅ **[영향성: 낮음] 현재 사업장 제원과 충돌하지 않습니다.**")
                st.markdown("입력하신 법안은 선택된 사업장의 PSM 제원 및 취급 물질 기준에 직접적인 제재를 가하지 않습니다.")
