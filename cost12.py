import streamlit as st
import pandas as pd
import altair as alt
from datetime import timedelta
import io
import re

# ---------------------------------------------------------
# 1. 데이터베이스: 사진 기반 [선택 II] 요금제 확정
# ---------------------------------------------------------
# 사진의 '선택 II' 요금표 수치 적용
RATES_DB = {
    '고압': { # 고압 선택 II
        'base_cost': 2580,
        'tou': {
            '봄가을': {'경부하': 80.2, '중간부하': 91.0,  '최대부하': 94.9},
            '여름':   {'경부하': 78.2, '중간부하': 113.0, '최대부하': 198.6},
            '겨울':   {'경부하': 95.2, '중간부하': 105.5, '최대부하': 172.4}
        }
    },
    '저압': { # 저압 선택 II
        'base_cost': 2390,
        'tou': {
            '봄가을': {'경부하': 85.4, '중간부하': 97.2,  '최대부하': 102.1},
            '여름':   {'경부하': 83.1, '중간부하': 140.0, '최대부하': 270.8},
            '겨울':   {'경부하': 105.8, '중간부하': 126.7, '최대부하': 227.0}
        }
    }
}

SEASONS = {
    3:'봄가을', 4:'봄가을', 5:'봄가을',
    6:'여름', 7:'여름', 8:'여름',
    9:'봄가을', 10:'봄가을',
    11:'겨울', 12:'겨울', 1:'겨울', 2:'겨울'
}

# ---------------------------------------------------------
# 2. 시간대 정의 (사진 내용 100% 반영)
# ---------------------------------------------------------
# 시간대 구분표 반영 (0:경부하, 1:중간부하, 2:최대부하)
# 0시~23시까지 순서대로 매핑

# 봄가을/여름 동일: 22~08 경부하 / 08~11 중간 / 11~12 최대 / 12~13 중간 / 13~18 최대 / 18~22 중간
TABLE_SPRING_SUMMER = (
    [0]*8 +       # 00~08 (8시간) 경부하
    [1]*3 +       # 08~11 (3시간) 중간
    [2]*1 +       # 11~12 (1시간) 최대
    [1]*1 +       # 12~13 (1시간) 중간
    [2]*5 +       # 13~18 (5시간) 최대
    [1]*4 +       # 18~22 (4시간) 중간
    [0]*2         # 22~24 (2시간) 경부하
)

# 겨울철: 22~08 경부하 / 08~09 중간 / 09~12 최대 / 12~16 중간 / 16~19 최대 / 19~22 중간
TABLE_WINTER = (
    [0]*8 +       # 00~08 (8시간) 경부하
    [1]*1 +       # 08~09 (1시간) 중간
    [2]*3 +       # 09~12 (3시간) 최대
    [1]*4 +       # 12~16 (4시간) 중간
    [2]*3 +       # 16~19 (3시간) 최대
    [1]*3 +       # 19~22 (3시간) 중간
    [0]*2         # 22~24 (2시간) 경부하
)

TIME_TABLE_MAP = {
    '봄가을': TABLE_SPRING_SUMMER,
    '여름':   TABLE_SPRING_SUMMER,
    '겨울':   TABLE_WINTER
}

LOAD_NAMES = ['경부하', '중간부하', '최대부하']
LOAD_COLORS = {'경부하': '#2ecc71', '중간부하': '#f1c40f', '최대부하': '#e74c3c'} 
VAT_RATE = 0.10

# ---------------------------------------------------------
# 3. 함수 정의
# ---------------------------------------------------------
def clean_number(value):
    if pd.isna(value): return 0
    s_val = str(value)
    clean_val = re.sub(r'[^\d.]', '', s_val)
    try: return float(clean_val)
    except ValueError: return 0

def find_column(columns, keywords):
    for col in columns:
        for key in keywords:
            if key in str(col).replace(" ", ""): return col
    return columns[0] if len(columns) > 0 else None

def get_load_type_idx(month, hour, weekday):
    """
    토요일/공휴일 조건 반영 로직
    weekday: 0(월)~6(일)
    """
    season = SEASONS[month]
    base_idx = TIME_TABLE_MAP[season][hour] # 0, 1, 2
    
    # 1. 일요일(6) 이면 -> 경부하(0)로 변경 (공휴일 조건)
    if weekday == 6:
        return 0
        
    # 2. 토요일(5) 이고 최대부하(2)이면 -> 중간부하(1)로 변경
    if weekday == 5 and base_idx == 2:
        return 1
        
    return base_idx

def calculate_tou_cost_photo(start, end, kwh, rate_table):
    if pd.isnull(start) or pd.isnull(end): return 0
    diff = end - start
    total_minutes = int(diff.total_seconds() / 60)
    if total_minutes <= 0: return 0
    
    kwh_per_min = kwh / total_minutes
    cost = 0
    curr = start
    
    for _ in range(total_minutes):
        month = curr.month
        hour = curr.hour
        weekday = curr.weekday() # 요일 확인
        
        # 요일 조건까지 반영된 부하 타입 조회
        idx = get_load_type_idx(month, hour, weekday)
        load_type = LOAD_NAMES[idx]
        season = SEASONS[month]
        
        price = rate_table[season][load_type]
        cost += price * kwh_per_min
        curr += timedelta(minutes=1)
    return cost

# ---------------------------------------------------------
# 4. 메인 화면 UI
# ---------------------------------------------------------
st.set_page_config(page_title="충전 수익성 분석기 (선택II)", layout="wide")

st.title("⚡ 충전 수익성 분석기 (사진 요금표 완벽반영)")
st.markdown("##### ✅ **[선택 II]** 요금제 + **토요일/일요일** 부하 조정 로직 적용됨")

with st.sidebar:
    st.header("1. 계약 조건")
    contract_type = st.radio("계약 종별 (사진 기준)", ('저압', '고압'), horizontal=True, help="사진에 있는 '선택 II' 요금제가 적용됩니다.")
    
    current_rates = RATES_DB[contract_type]['tou']
    default_base_cost = RATES_DB[contract_type]['base_cost']
    
    contract_power = st.number_input("계약 전력 (kW)", value=100)
    base_rate_unit = st.number_input("기본요금 단가", value=default_base_cost, disabled=True)
    
    st.divider()
    st.header("2. 변동비/손실 설정")
    fuel_adj_rate = st.number_input("연료비조정단가 (원)", value=5.0)
    climate_rate = st.number_input("기후환경요금 (원)", value=9.0)
    fund_rate_percent = st.number_input("전력기금 (%)", value=3.7, step=0.1)
    FUND_RATE = fund_rate_percent / 100
    loss_rate = st.number_input("충전 손실률 (%)", value=5.0)
    etc_cost_input = st.number_input("원단위 절사/보정 (원)", value=0)

    st.divider()
    st.header("🧹 데이터 필터")
    filter_min_minutes = st.number_input("최소 충전 시간 (분)", value=3)
    filter_min_kwh = st.number_input("최소 충전량 (kWh)", value=0.5)
    
    base_cost_final = (contract_power * base_rate_unit) * (1 + VAT_RATE + FUND_RATE)

uploaded_file = st.file_uploader("엑셀 데이터 업로드", type=['xlsx', 'xls'])

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        cols = df.columns.tolist()
        
        c1, c2, c3, c4 = st.columns(4)
        start_col = c1.selectbox("시작 시간", cols, index=cols.index(find_column(cols, ['시작', 'Start'])) if find_column(cols, ['시작', 'Start']) else 0)
        end_col = c2.selectbox("종료 시간", cols, index=cols.index(find_column(cols, ['종료', 'End'])) if find_column(cols, ['종료', 'End']) else 0)
        kwh_col = c3.selectbox("충전량", cols, index=cols.index(find_column(cols, ['충전량', 'kWh'])) if find_column(cols, ['충전량', 'kWh']) else 0)
        
        price_col_guess = find_column(cols, ['단가', 'Price'])
        use_price_col = c4.checkbox("엑셀 판매단가 사용", value=bool(price_col_guess))
        if use_price_col:
            price_col = c4.selectbox("판매단가 컬럼", cols, index=cols.index(price_col_guess) if price_col_guess else 0)
        else:
            manual_price = c4.number_input("고정 판매단가 (원)", value=300)

        if st.button("🚀 정밀 분석 시작"):
            with st.spinner('선택II 요금제 및 주말 특례 적용 중...'):
                raw_df = df.copy()
                
                raw_df['분석_시작'] = pd.to_datetime(raw_df[start_col], errors='coerce')
                raw_df['분석_종료'] = pd.to_datetime(raw_df[end_col], errors='coerce')
                raw_df['분석_충전량'] = raw_df[kwh_col].apply(clean_number)
                raw_df['충전시간(분)'] = (raw_df['분석_종료'] - raw_df['분석_시작']).dt.total_seconds() / 60
                
                valid_df = raw_df.dropna(subset=['분석_시작', '분석_종료'])
                clean_df = valid_df[
                    (valid_df['충전시간(분)'] >= filter_min_minutes) & 
                    (valid_df['분석_충전량'] >= filter_min_kwh)
                ].copy()

                # 손실 반영 매입량
                clean_df['판매_전력량'] = clean_df['분석_충전량']
                clean_df['매입_전력량'] = clean_df['판매_전력량'] * (1 + loss_rate / 100)
                
                # 비용 계산 (사진기반 함수 적용)
                clean_df['TOU요금'] = clean_df.apply(lambda x: calculate_tou_cost_photo(x['분석_시작'], x['분석_종료'], x['매입_전력량'], current_rates), axis=1)
                clean_df['기후_연료비'] = clean_df['매입_전력량'] * (climate_rate + fuel_adj_rate)
                clean_df['변동비_세후'] = (clean_df['TOU요금'] + clean_df['기후_연료비']) * (1 + VAT_RATE + FUND_RATE)
                
                clean_df['원가(원/kWh)'] = clean_df.apply(lambda x: x['변동비_세후'] / x['판매_전력량'] if x['판매_전력량'] > 0 else 0, axis=1)

                if use_price_col:
                    clean_df['매출액'] = clean_df['판매_전력량'] * clean_df[price_col].apply(clean_number)
                else:
                    clean_df['매출액'] = clean_df['판매_전력량'] * manual_price

                total_sales = clean_df['매출액'].sum()
                total_cost_bill = clean_df['변동비_세후'].sum() + base_cost_final + etc_cost_input
                operating_profit = total_sales - total_cost_bill
                
                # 결과 리포트
                st.divider()
                st.subheader("📊 분석 결과 (사진 기준)")
                
                m1, m2, m3 = st.columns(3)
                m1.metric("총 매출", f"{int(total_sales):,}원")
                m2.metric("총 비용", f"{int(total_cost_bill):,}원")
                m3.metric("영업이익", f"{int(operating_profit):,}원")
                
                st.divider()
                st.subheader("📝 상세 데이터 (히트맵)")
                st.caption("※ **토요일/일요일 할인**이 자동으로 적용되어 계산되었습니다.")
                
                display_df = clean_df[['분석_시작', '판매_전력량', '매입_전력량', '매출액', '변동비_세후', '원가(원/kWh)']].copy()
                display_df.columns = ['충전시작', '판매량', '매입량(+손실)', '매출', '변동원가', '단가']
                
                try:
                    st.dataframe(
                        display_df.style.format({
                            '판매량': '{:.2f}', '매입량(+손실)': '{:.2f}', '매출': '{:,.0f}', '변동원가': '{:,.0f}', '단가': '{:.0f}'
                        }).background_gradient(subset=['단가'], cmap='Reds'),
                        use_container_width=True, height=600
                    )
                except:
                    st.dataframe(display_df, use_container_width=True, height=600)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    clean_df.to_excel(writer, index=False)
                st.download_button("📥 엑셀 다운로드", data=output.getvalue(), file_name="최종분석.xlsx")

    except Exception as e:
        st.error(f"오류: {e}")