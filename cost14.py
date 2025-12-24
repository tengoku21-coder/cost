import streamlit as st
import pandas as pd
import altair as alt
from datetime import timedelta
import io
import re

# ---------------------------------------------------------
# 1. 데이터베이스: [선택 II] 요금제 확정 (사진 반영)
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

# ---------------------------------------------------------
# 2. 시간대 정의 (사진 내용 100% 반영)
# ---------------------------------------------------------
# 봄가을/여름
TABLE_SPRING_SUMMER = ([0]*8 + [1]*3 + [2]*1 + [1]*1 + [2]*5 + [1]*4 + [0]*2)
# 겨울
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
    season = SEASONS[month]
    base_idx = TIME_TABLE_MAP[season][hour]
    
    # 토요일/공휴일 특례 적용
    if weekday == 6: # 일요일 -> 경부하
        return 0
    if weekday == 5 and base_idx == 2: # 토요일 최대부하 -> 중간부하
        return 1
    return base_idx

def get_load_type_name(month, hour, weekday=0):
    idx = get_load_type_idx(month, hour, weekday)
    return LOAD_NAMES[idx]

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
        weekday = curr.weekday()
        
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
st.set_page_config(page_title="충전 수익성 분석기 (v16.0)", layout="wide")

st.title("⚡ 충전 수익성 분석기 (4대 핵심지표 포함)")
st.markdown("##### 📊 [선택II] 정밀요금 + 📉 손실반영 + 📈 4대 핵심 단가 분석")

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
            with st.spinner('정밀 계산 및 4대 지표 산출 중...'):
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

                # 손실 반영
                clean_df['판매_전력량'] = clean_df['분석_충전량']
                clean_df['매입_전력량'] = clean_df['판매_전력량'] * (1 + loss_rate / 100)
                
                # 비용 계산
                clean_df['TOU요금'] = clean_df.apply(lambda x: calculate_tou_cost_photo(x['분석_시작'], x['분석_종료'], x['매입_전력량'], current_rates), axis=1)
                clean_df['기후_연료비'] = clean_df['매입_전력량'] * (climate_rate + fuel_adj_rate)
                clean_df['변동비_세후'] = (clean_df['TOU요금'] + clean_df['기후_연료비']) * (1 + VAT_RATE + FUND_RATE)
                
                # 1kWh당 원가 (판매량 기준 역산)
                clean_df['원가(원/kWh)'] = clean_df.apply(lambda x: x['변동비_세후'] / x['판매_전력량'] if x['판매_전력량'] > 0 else 0, axis=1)

                if use_price_col:
                    clean_df['매출액'] = clean_df['판매_전력량'] * clean_df[price_col].apply(clean_number)
                else:
                    clean_df['매출액'] = clean_df['판매_전력량'] * manual_price

                # 집계
                total_sales = clean_df['매출액'].sum()
                total_cost_bill = clean_df['변동비_세후'].sum() + base_cost_final + etc_cost_input
                operating_profit = total_sales - total_cost_bill
                total_sold_kwh = clean_df['판매_전력량'].sum()
                
                # ----------------------------------------
                # [핵심] 4대 단가 지표 계산
                # ----------------------------------------
                if total_sold_kwh > 0:
                    # 1. 평균 전력량 요금 (변동비)
                    avg_var_cost = clean_df['변동비_세후'].sum() / total_sold_kwh
                    # 2. BEP 요금 (총원가 / 판매량)
                    bep_cost = total_cost_bill / total_sold_kwh
                    # 3. 최고 비싼 충전 요금
                    max_cost = clean_df['원가(원/kWh)'].max()
                    # 4. 최고 싼 충전 요금
                    min_cost = clean_df[clean_df['원가(원/kWh)'] > 10]['원가(원/kWh)'].min() # 0원 제외
                    if pd.isna(min_cost): min_cost = 0
                else:
                    avg_var_cost = 0; bep_cost = 0; max_cost = 0; min_cost = 0;

                # ------------------------------------
                # 결과 리포트
                # ------------------------------------
                st.divider()
                st.subheader("📊 경영 성과 (총액)")
                m1, m2, m3 = st.columns(3)
                m1.metric("총 매출", f"{int(total_sales):,}원")
                m2.metric("총 비용 (손실포함)", f"{int(total_cost_bill):,}원")
                m3.metric("영업이익", f"{int(operating_profit):,}원", 
                          delta=f"{(operating_profit/total_sales*100):.1f}%" if total_sales > 0 else "0%")
                
                st.divider()
                st.subheader("💡 1kWh당 핵심 단가 분석 (4대 지표)")
                
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("평균 전력량요금", f"{int(avg_var_cost)}원/kWh", help="순수 전기요금(변동비) 평균")
                k2.metric("BEP 요금 (손익분기)", f"{int(bep_cost)}원/kWh", delta="기본료 포함", delta_color="off", help="이 금액 이상 받아야 적자 면함")
                k3.metric("최고 비싼 충전", f"{int(max_cost)}원/kWh", help="최대부하 시간대에 충전된 건 중 가장 비싼 값")
                k4.metric("최고 싼 충전", f"{int(min_cost)}원/kWh", help="경부하 시간대에 충전된 건 중 가장 싼 값")
                
                # 그래프 생성
                if not clean_df.empty:
                    st.divider()
                    st.subheader("📈 시간대별 사용 패턴")
                    
                    clean_df['StartHour'] = clean_df['분석_시작'].dt.hour
                    rep_month = clean_df['분석_시작'].dt.month.iloc[0]
                    hourly_stats = clean_df.groupby('StartHour')['판매_전력량'].sum().reindex(range(24), fill_value=0).reset_index()
                    hourly_stats.columns = ['시간(Hour)', '총충전량(kWh)']
                    hourly_stats['요금구간'] = hourly_stats['시간(Hour)'].apply(lambda h: get_load_type_name(rep_month, h))
                    
                    chart = alt.Chart(hourly_stats).mark_bar().encode(
                        x=alt.X('시간(Hour):O', title='시간 (0시~23시)', axis=alt.Axis(labelAngle=0)),
                        y=alt.Y('총충전량(kWh):Q', title='총 판매량 (kWh)'),
                        color=alt.Color('요금구간:N', 
                                      scale=alt.Scale(domain=list(LOAD_COLORS.keys()), range=list(LOAD_COLORS.values())),
                                      legend=alt.Legend(title="요금 구간")),
                        tooltip=['시간(Hour)', '총충전량(kWh)', '요금구간']
                    ).properties(height=350)
                    st.altair_chart(chart, use_container_width=True)

                st.divider()
                st.subheader("📝 상세 데이터 (히트맵)")
                st.caption("※ **매입량**은 손실률(5%)이 반영된 수치이며, **단가**가 붉을수록 원가가 비싼 건입니다.")
                
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
                st.download_button("📥 엑셀 다운로드", data=output.getvalue(), file_name="최종분석결과.xlsx")

    except Exception as e:
        st.error(f"오류: {e}")