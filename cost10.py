import streamlit as st
import pandas as pd
import altair as alt  # 차트 생성을 위한 라이브러리
from datetime import timedelta
import io
import re

# ---------------------------------------------------------
# 1. 데이터베이스 & 설정
# ---------------------------------------------------------
RATES_DB = {
    '고압': {
        'base_cost': 2580,
        'tou': {
            '봄가을': {'경부하': 66.8, '중간부하': 85.8,  '최대부하': 106.3},
            '여름':   {'경부하': 66.8, '중간부하': 116.4, '최대부하': 198.7},
            '겨울':   {'경부하': 79.5, '중간부하': 120.2, '최대부하': 184.2}
        }
    },
    '저압': {
        'base_cost': 2390,
        'tou': {
            '봄가을': {'경부하': 73.0, '중간부하': 93.8,  '최대부하': 116.1},
            '여름':   {'경부하': 73.0, '중간부하': 127.3, '최대부하': 217.2},
            '겨울':   {'경부하': 86.9, '중간부하': 131.4, '최대부하': 201.3}
        }
    }
}

SEASONS = {
    3:'봄가을', 4:'봄가을', 5:'봄가을',
    6:'여름', 7:'여름', 8:'여름',
    9:'봄가을', 10:'봄가을',
    11:'겨울', 12:'겨울', 1:'겨울', 2:'겨울'
}

TIME_TABLE_IDX = {
    '봄가을': [0]*8 + [1]*3 + [2]*2 + [1]*4 + [2]*3 + [1]*4,
    '여름':   [0]*8 + [1]*3 + [2]*2 + [1]*4 + [2]*3 + [1]*4,
    '겨울':   [0]*8 + [1]*3 + [2]*2 + [1]*4 + [2]*3 + [1]*4
}
LOAD_NAMES = ['경부하', '중간부하', '최대부하']
# 그래프 색상 매핑 (경부하:초록, 중간:노랑, 최대:빨강)
LOAD_COLORS = {'경부하': '#2ecc71', '중간부하': '#f1c40f', '최대부하': '#e74c3c'} 

VAT_RATE = 0.10

# ---------------------------------------------------------
# 2. 함수 정의
# ---------------------------------------------------------
def find_column(columns, keywords):
    for col in columns:
        for key in keywords:
            if key in str(col).replace(" ", ""): return col
    return columns[0] if len(columns) > 0 else None

def clean_number(value):
    if pd.isna(value): return 0
    s_val = str(value)
    clean_val = re.sub(r'[^\d.]', '', s_val)
    try: return float(clean_val)
    except ValueError: return 0

def calculate_tou_cost_dynamic(start, end, kwh, rate_table):
    if pd.isnull(start) or pd.isnull(end): return 0
    diff = end - start
    total_minutes = int(diff.total_seconds() / 60)
    if total_minutes <= 0: return 0
    
    kwh_per_min = kwh / total_minutes
    cost = 0
    curr = start
    for _ in range(total_minutes):
        month = curr.month
        season = SEASONS[month]
        idx = TIME_TABLE_IDX[season][curr.hour]
        load_type = LOAD_NAMES[idx]
        price = rate_table[season][load_type]
        cost += price * kwh_per_min
        curr += timedelta(minutes=1)
    return cost

def get_load_type(month, hour):
    season = SEASONS[month]
    idx = TIME_TABLE_IDX[season][hour]
    return LOAD_NAMES[idx]

# ---------------------------------------------------------
# 3. 메인 화면 UI
# ---------------------------------------------------------
st.set_page_config(page_title="충전 사업 통합 분석기", layout="wide")

st.title("⚡ 충전 사업 통합 수익성 분석기 (Visual Ver.)")
st.markdown("##### 📊 시간대별 사용 패턴 그래프 + 수익성 분석 + 히트맵")

# 사이드바
with st.sidebar:
    st.header("1. 계약 조건")
    contract_type = st.radio("계약 종별 선택", ('저압', '고압'), horizontal=True)
    
    current_rates = RATES_DB[contract_type]['tou']
    default_base_cost = RATES_DB[contract_type]['base_cost']
    
    contract_power = st.number_input("계약 전력 (kW)", value=100)
    base_rate_unit = st.number_input("기본요금 단가", value=default_base_cost, disabled=True)
    
    st.divider()
    st.header("2. 변동비 설정")
    fuel_adj_rate = st.number_input("연료비조정단가 (원)", value=5.0)
    climate_rate = st.number_input("기후환경요금 (원)", value=9.0)
    fund_rate_percent = st.number_input("전력기금 (%)", value=3.7, step=0.1)
    FUND_RATE = fund_rate_percent / 100
    etc_cost_input = st.number_input("원단위 절사/보정 (원)", value=0)

    st.divider()
    st.header("🧹 데이터 전처리")
    filter_min_minutes = st.number_input("최소 충전 시간 (분)", value=3)
    filter_min_kwh = st.number_input("최소 충전량 (kWh)", value=0.5)
    
    base_cost_final = (contract_power * base_rate_unit) * (1 + VAT_RATE + FUND_RATE)

# 메인 파일 업로드
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

        if st.button(f"🚀 {contract_type} 기준 전체 분석 시작"):
            with st.spinner('정밀 분석 및 그래프 생성 중...'):
                raw_df = df.copy()
                
                # 전처리 및 필터링
                raw_df['분석_시작'] = pd.to_datetime(raw_df[start_col], errors='coerce')
                raw_df['분석_종료'] = pd.to_datetime(raw_df[end_col], errors='coerce')
                raw_df['분석_충전량'] = raw_df[kwh_col].apply(clean_number)
                raw_df['충전시간(분)'] = (raw_df['분석_종료'] - raw_df['분석_시작']).dt.total_seconds() / 60
                
                valid_df = raw_df.dropna(subset=['분석_시작', '분석_종료'])
                clean_df = valid_df[
                    (valid_df['충전시간(분)'] >= filter_min_minutes) & 
                    (valid_df['분석_충전량'] >= filter_min_kwh)
                ].copy()
                
                removed_count = len(raw_df) - len(clean_df)

                # 비용 및 단가 계산
                clean_df['TOU요금'] = clean_df.apply(lambda x: calculate_tou_cost_dynamic(x['분석_시작'], x['분석_종료'], x['분석_충전량'], current_rates), axis=1)
                clean_df['기후_연료비'] = clean_df['분석_충전량'] * (climate_rate + fuel_adj_rate)
                clean_df['변동비_세전'] = clean_df['TOU요금'] + clean_df['기후_연료비']
                clean_df['변동비_세후'] = clean_df['변동비_세전'] * (1 + VAT_RATE + FUND_RATE)
                clean_df['원가(원/kWh)'] = clean_df.apply(lambda x: x['변동비_세후'] / x['분석_충전량'] if x['분석_충전량'] > 0 else 0, axis=1)

                # 매출 계산
                if use_price_col:
                    clean_df['매출액'] = clean_df['분석_충전량'] * clean_df[price_col].apply(clean_number)
                else:
                    clean_df['매출액'] = clean_df['분석_충전량'] * manual_price

                # 집계
                total_kwh = clean_df['분석_충전량'].sum()
                total_sales = clean_df['매출액'].sum()
                total_cost_bill = clean_df['변동비_세후'].sum() + base_cost_final + etc_cost_input
                operating_profit = total_sales - total_cost_bill
                
                avg_variable_unit = clean_df['변동비_세후'].sum() / total_kwh if total_kwh > 0 else 0
                avg_total_unit = total_cost_bill / total_kwh if total_kwh > 0 else 0

                # ------------------------------------
                # [NEW] 시간대별 충전 분포 데이터 생성
                # ------------------------------------
                if not clean_df.empty:
                    # 시작 시간의 '시(Hour)' 추출
                    clean_df['StartHour'] = clean_df['분석_시작'].dt.hour
                    # 대표 월(Season 판단용) - 데이터의 첫 번째 달 사용
                    rep_month = clean_df['분석_시작'].dt.month.iloc[0]
                    
                    # 시간대별 그룹핑
                    hourly_stats = clean_df.groupby('StartHour')['분석_충전량'].sum().reindex(range(24), fill_value=0).reset_index()
                    hourly_stats.columns = ['시간(Hour)', '총충전량(kWh)']
                    
                    # 부하 시간대 정보 추가 (색상용)
                    hourly_stats['부하구분'] = hourly_stats['시간(Hour)'].apply(lambda h: get_load_type(rep_month, h))
                    
                    # 차트 생성 (Altair)
                    chart = alt.Chart(hourly_stats).mark_bar().encode(
                        x=alt.X('시간(Hour):O', title='시간 (0시~23시)', axis=alt.Axis(labelAngle=0)),
                        y=alt.Y('총충전량(kWh):Q', title='총 충전량 (kWh)'),
                        color=alt.Color('부하구분:N', scale=alt.Scale(domain=list(LOAD_COLORS.keys()), range=list(LOAD_COLORS.values())), title='요금 구간'),
                        tooltip=['시간(Hour)', '총충전량(kWh)', '부하구분']
                    ).properties(
                        title='🕒 시간대별 충전량 분포 (Total kWh)',
                        height=350
                    )
                
                # ------------------------------------
                # 결과 리포트
                # ------------------------------------
                st.divider()
                st.subheader("📊 종합 분석 대시보드")
                
                m1, m2, m3 = st.columns(3)
                m1.metric("총 매출액", f"{int(total_sales):,}원")
                m2.metric("총 비용 (기본료+변동비)", f"{int(total_cost_bill):,}원")
                m3.metric("영업이익", f"{int(operating_profit):,}원", 
                          delta=f"{(operating_profit/total_sales*100):.1f}%" if total_sales > 0 else "0%")
                
                st.divider()
                
                # [NEW] 그래프 표시 영역
                st.subheader("📈 시간대별 사용 패턴")
                st.caption("어떤 시간대에 충전이 많이 일어나는지, 해당 시간대가 비싼 구간(빨강)인지 싼 구간(초록)인지 확인하세요.")
                if not clean_df.empty:
                    st.altair_chart(chart, use_container_width=True)
                else:
                    st.warning("데이터가 없어 그래프를 그릴 수 없습니다.")

                st.divider()
                st.subheader("💡 단가 정밀 분석")
                k1, k2, k3 = st.columns(3)
                k1.metric("평균 변동 단가", f"{int(avg_variable_unit)}원/kWh")
                k2.metric("손익분기점(BEP)", f"{int(avg_total_unit)}원/kWh", delta="목표")
                
                if not clean_df.empty:
                    max_unit = clean_df['원가(원/kWh)'].max()
                    k3.metric("최고 비싼 충전", f"{int(max_unit)}원/kWh")
                
                st.divider()
                st.subheader("📝 상세 데이터 (히트맵)")
                
                display_df = clean_df[['분석_시작', '충전시간(분)', '분석_충전량', '매출액', '원가(원/kWh)']].copy()
                display_df.columns = ['충전시작', '분', 'kWh', '매출', '단가']
                
                st.dataframe(
                    display_df.style.format({
                        '분': '{:.0f}', 'kWh': '{:.2f}', '매출': '{:,.0f}', '단가': '{:.0f}'
                    }).background_gradient(subset=['단가'], cmap='Reds'),
                    use_container_width=True,
                    height=500
                )
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    clean_df.to_excel(writer, index=False, sheet_name='분석결과')
                st.download_button("📥 전체 결과 다운로드", data=output.getvalue(), file_name="최종분석결과.xlsx")

    except Exception as e:
        st.error(f"오류: {e}")