import streamlit as st
import pandas as pd
import altair as alt
from datetime import timedelta
import io
import re

# ---------------------------------------------------------
# 1. 데이터베이스: [선택 II] 요금제 확정
# ---------------------------------------------------------
RATES_DB = {
    '고압': {
        'base_cost': 2580,
        'tou': {
            '봄가을': {'경부하': 80.2, '중간부하': 91.0,  '최대부하': 94.9},
            '여름':   {'경부하': 78.2, '중간부하': 113.0, '최대부하': 198.6},
            '겨울':   {'경부하': 95.2, '중간부하': 105.5, '최대부하': 172.4}
        }
    },
    '저압': {
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

# 시간대 정의
TABLE_SPRING_SUMMER = ([0]*8 + [1]*3 + [2]*1 + [1]*1 + [2]*5 + [1]*4 + [0]*2)
TABLE_WINTER = ([0]*8 + [1]*1 + [2]*3 + [1]*4 + [2]*3 + [1]*3 + [0]*2)

TIME_TABLE_MAP = {
    '봄가을': TABLE_SPRING_SUMMER,
    '여름':   TABLE_SPRING_SUMMER,
    '겨울':   TABLE_WINTER
}

LOAD_NAMES = ['경부하', '중간부하', '최대부하']
LOAD_COLORS = {'경부하': '#2ecc71', '중간부하': '#f1c40f', '최대부하': '#e74c3c'} 
VAT_RATE = 0.10

# ---------------------------------------------------------
# 2. 함수 정의
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
    season = SEASONS[month]
    base_idx = TIME_TABLE_MAP[season][hour]
    if weekday == 6: return 0 # 일요일
    if weekday == 5 and base_idx == 2: return 1 # 토요일
    return base_idx

def get_load_type_name(month, hour, weekday=0):
    idx = get_load_type_idx(month, hour, weekday)
    return LOAD_NAMES[idx]

def calculate_tou_cost_photo(start, end, kwh, rate_table):
    if pd.isnull(start) or pd.isnull(end): return 0, 0
    diff = end - start
    total_minutes = int(diff.total_seconds() / 60)
    if total_minutes <= 0: return 0, 0
    
    kwh_per_min = kwh / total_minutes
    cost = 0
    
    # 순수 요금표 단가 계산용
    tou_rate_accum = 0 
    
    curr = start
    for _ in range(total_minutes):
        month = curr.month
        hour = curr.hour
        weekday = curr.weekday()
        
        idx = get_load_type_idx(month, hour, weekday)
        load_type = LOAD_NAMES[idx]
        season = SEASONS[month]
        
        price = rate_table[season][load_type]
        
        cost += price * kwh_per_min
        tou_rate_accum += price # 단가 누적
        curr += timedelta(minutes=1)
        
    # 평균 적용 단가 (순수 요금표 기준)
    avg_tou_rate = tou_rate_accum / total_minutes
    
    return cost, avg_tou_rate

# ---------------------------------------------------------
# 3. 메인 화면 UI
# ---------------------------------------------------------
st.set_page_config(page_title="충전 수익성 분석기 (v20.0)", layout="wide")

st.title("⚡ 충전 수익성 분석기 (근거 제시형)")
st.markdown("##### 📊 가중평균 산출 근거 제공 + 전력기금 2.7% 적용 완료")

with st.sidebar:
    st.header("1. 계약 조건")
    contract_type = st.radio("계약 종별 (사진 기준)", ('저압', '고압'), horizontal=True)
    
    current_rates = RATES_DB[contract_type]['tou']
    default_base_cost = RATES_DB[contract_type]['base_cost']
    
    contract_power = st.number_input("계약 전력 (kW)", value=100)
    base_rate_unit = st.number_input("기본요금 단가", value=default_base_cost, disabled=True)
    
    st.divider()
    st.header("2. 변동비/손실 설정")
    fuel_adj_rate = st.number_input("연료비조정단가 (원)", value=5.0)
    climate_rate = st.number_input("기후환경요금 (원)", value=9.0)
    
    # [수정] 전력기금 기본값 2.7%로 변경
    fund_rate_percent = st.number_input("전력기금 (%)", value=2.7, step=0.1)
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

        if st.button("🚀 분석 시작"):
            with st.spinner('요금표 기준 단가 산출 중...'):
                raw_df = df.copy()
                
                # 전처리
                raw_df['분석_시작'] = pd.to_datetime(raw_df[start_col], errors='coerce')
                raw_df['분석_종료'] = pd.to_datetime(raw_df[end_col], errors='coerce')
                raw_df['분석_충전량'] = raw_df[kwh_col].apply(clean_number)
                raw_df['충전시간(분)'] = (raw_df['분석_종료'] - raw_df['분석_시작']).dt.total_seconds() / 60
                
                valid_df = raw_df.dropna(subset=['분석_시작', '분석_종료'])
                clean_df = valid_df[
                    (valid_df['충전시간(분)'] >= filter_min_minutes) & 
                    (valid_df['분석_충전량'] >= filter_min_kwh)
                ].copy()

                # 손실 반영 (수익 계산용)
                clean_df['판매_전력량'] = clean_df['분석_충전량']
                clean_df['매입_전력량'] = clean_df['판매_전력량'] * (1 + loss_rate / 100)
                
                # 비용 계산
                cost_results = clean_df.apply(lambda x: calculate_tou_cost_photo(x['분석_시작'], x['분석_종료'], x['매입_전력량'], current_rates), axis=1, result_type='expand')
                
                clean_df['TOU요금_실제'] = cost_results[0]
                clean_df['요금표단가'] = cost_results[1] # 순수 한전 단가
                
                clean_df['기후_연료비'] = clean_df['매입_전력량'] * (climate_rate + fuel_adj_rate)
                clean_df['변동비_세후_총액'] = (clean_df['TOU요금_실제'] + clean_df['기후_연료비']) * (1 + VAT_RATE + FUND_RATE)
                
                if use_price_col:
                    clean_df['매출액'] = clean_df['판매_전력량'] * clean_df[price_col].apply(clean_number)
                else:
                    clean_df['매출액'] = clean_df['판매_전력량'] * manual_price

                # 집계 (돈 계산)
                total_sales = clean_df['매출액'].sum()
                total_cost_bill = clean_df['변동비_세후_총액'].sum() + base_cost_final + etc_cost_input
                operating_profit = total_sales - total_cost_bill
                total_sold_kwh = clean_df['판매_전력량'].sum()
                
                # 집계 (단가 분석 - 요금표 기준)
                if total_sold_kwh > 0:
                    # 가중평균 계산을 위한 분자 (순수 요금표 단가 * 판매량의 총합)
                    sum_weighted_tou = (clean_df['요금표단가'] * clean_df['판매_전력량']).sum()
                    weighted_avg_rate = sum_weighted_tou / total_sold_kwh
                    
                    max_rate = clean_df['요금표단가'].max()
                    min_rate = clean_df[clean_df['요금표단가'] > 0]['요금표단가'].min()
                    
                    # BEP (실제 비용 기준)
                    bep_cost = total_cost_bill / total_sold_kwh
                else:
                    sum_weighted_tou=0; weighted_avg_rate=0; max_rate=0; min_rate=0; bep_cost=0;

                # ------------------------------------
                # 결과 리포트
                # ------------------------------------
                st.divider()
                st.subheader("📊 경영 성과 (전력기금 2.7% 적용됨)")
                m1, m2, m3 = st.columns(3)
                m1.metric("총 매출", f"{int(total_sales):,}원")
                m2.metric("총 비용", f"{int(total_cost_bill):,}원")
                m3.metric("영업이익", f"{int(operating_profit):,}원", 
                          delta=f"{(operating_profit/total_sales*100):.1f}%" if total_sales > 0 else "0%")
                
                st.divider()
                st.subheader("💡 1kWh당 단가 분석 (순수 요금표 기준)")
                
                # [NEW] 가중평균 산출 근거 패널
                with st.expander("🔍 평균 요금표 단가 산출 근거 보기 (클릭)", expanded=False):
                    st.write("**[공식]** `(각 충전건별 요금표단가 × 충전량)의 합계` ÷ `총 충전량`")
                    st.write(f"1. 순수 요금표 기준 총합 (분자): **{int(sum_weighted_tou):,}원**")
                    st.write(f"2. 총 충전량 (분모): **{int(total_sold_kwh):,}kWh**")
                    st.markdown(f"👉 **{int(sum_weighted_tou)}** ÷ **{int(total_sold_kwh)}** = **{int(weighted_avg_rate)}원/kWh**")
                    st.info("단순히 요금표 숫자를 더해서 나눈 게 아니라, **'실제 얼마나 충전했는지'** 비중을 따져서 계산한 값입니다.")

                k1, k2, k3, k4 = st.columns(4)
                k1.metric("평균 요금표 단가", f"{int(weighted_avg_rate)}원/kWh", help="위 산출 근거를 확인하세요.")
                k2.metric("최고 비싼 시간", f"{max_rate:.1f}원/kWh", help="요금표상 가장 비싼 구간")
                k3.metric("최고 싼 시간", f"{min_rate:.1f}원/kWh", help="요금표상 가장 싼 구간")
                k4.metric("BEP (목표단가)", f"{int(bep_cost)}원/kWh", delta="실비용 기준", delta_color="off", help="BEP는 실제 나가는 돈(세금포함) 기준이어야 하므로 높게 나옵니다.")

                # 그래프
                if not clean_df.empty:
                    st.divider()
                    st.subheader("📈 시간대별 사용 패턴")
                    clean_df['StartHour'] = clean_df['분석_시작'].dt.hour
                    rep_month = clean_df['분석_시작'].dt.month.iloc[0]
                    hourly_stats = clean_df.groupby('StartHour')['판매_전력량'].sum().reindex(range(24), fill_value=0).reset_index()
                    hourly_stats.columns = ['시간(Hour)', '총충전량(kWh)']
                    hourly_stats['요금구간'] = hourly_stats['시간(Hour)'].apply(lambda h: get_load_type_name(rep_month, h))
                    
                    chart = alt.Chart(hourly_stats).mark_bar().encode(
                        x=alt.X('시간(Hour):O', axis=alt.Axis(labelAngle=0)),
                        y=alt.Y('총충전량(kWh):Q'),
                        color=alt.Color('요금구간:N', scale=alt.Scale(domain=list(LOAD_COLORS.keys()), range=list(LOAD_COLORS.values()))),
                        tooltip=['시간(Hour)', '총충전량(kWh)', '요금구간']
                    ).properties(height=350)
                    st.altair_chart(chart, use_container_width=True)

                st.divider()
                st.subheader("📝 상세 데이터")
                
                display_df = clean_df[['분석_시작', '판매_전력량', '요금표단가', '매출액', '변동비_세후_총액']].copy()
                display_df.columns = ['충전시작', '판매량(kWh)', '한전단가(표준)', '매출', '실제원가총액(세금포함)']
                
                try:
                    st.dataframe(
                        display_df.style.format({
                            '판매량(kWh)': '{:.2f}', 
                            '한전단가(표준)': '{:.1f}',
                            '매출': '{:,.0f}', 
                            '실제원가총액(세금포함)': '{:,.0f}'
                        }).background_gradient(subset=['한전단가(표준)'], cmap='Reds'),
                        use_container_width=True, height=600
                    )
                except:
                    st.dataframe(display_df, use_container_width=True, height=600)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    clean_df.to_excel(writer, index=False)
                st.download_button("📥 엑셀 다운로드", data=output.getvalue(), file_name="분석결과_최종.xlsx")

    except Exception as e:
        st.error(f"오류: {e}")