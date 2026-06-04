from datetime import datetime, timedelta
import os
import time
import pandas as pd
import FinanceDataReader as fdr
import yfinance as yf
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# 스크립트 위치 기준 상위 루트 디렉토리 구하기 (사이드 이펙트 방지)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 데이터 보관용 로컬 CSV 파일 경로를 절대 경로로 정의
DB_FILE = os.path.join(BASE_DIR, "db", "60day_high_yf.csv")

def get_market_business_days(start_date, end_date):
    """삼성전자(005930.KS) 데이터를 기준으로 실제 주식시장 영업일 목록을 가져옵니다."""
    try:
        start_dt = datetime.strptime(start_date, "%Y%m%d").strftime("%Y-%m-%d")
        end_dt = (datetime.strptime(end_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        df = yf.download("005930.KS", start=start_dt, end=end_dt, progress=False)
        # 멀티인덱스 컬럼 구조 단순화
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.droplevel(1)
        return df.index.strftime("%Y%m%d").tolist()
    except Exception as e:
        print(f"[WARN] 영업일 목록 조회 실패: {e}")
        # 예외 발생 시 주말을 제외한 날짜 기준으로 대체
        s = datetime.strptime(start_date, "%Y%m%d")
        e = datetime.strptime(end_date, "%Y%m%d")
        delta = e - s
        all_days = [(s + timedelta(days=i)).strftime("%Y%m%d") for i in range(delta.days + 1)]
        business_days = [d for d in all_days if datetime.strptime(d, "%Y%m%d").weekday() < 5]
        return business_days

def parse_yfinance_chunk(df_chunk, ticker_map_reverse):
    """yf.download 결과인 MultiIndex DataFrame을 [날짜, 종목코드, 시가, 고가, 저가, 종가, 거래량] 형태로 변환"""
    if df_chunk.empty:
        return pd.DataFrame()
    
    if not isinstance(df_chunk.columns, pd.MultiIndex):
        ticker_name = df_chunk.columns.name or "UNKNOWN"
        df_chunk.columns = pd.MultiIndex.from_product([[ticker_name], df_chunk.columns])
        
    try:
        # Pandas 2.1.0+ future_stack warning 방지 및 호환성 확보
        try:
            df_stacked = df_chunk.stack(level=0, future_stack=True)
        except Exception:
            df_stacked = df_chunk.stack(level=0)
            
        df_stacked = df_stacked.reset_index()
        
        rename_map = {}
        for col in df_stacked.columns:
            col_lower = str(col).lower()
            if col_lower == 'date':
                rename_map[col] = '날짜'
            elif col_lower in ['ticker', 'level_1', 'level_0'] or col == df_chunk.columns.names[0]:
                rename_map[col] = 'yf_ticker'
            elif col_lower == 'open':
                rename_map[col] = '시가'
            elif col_lower == 'high':
                rename_map[col] = '고가'
            elif col_lower == 'low':
                rename_map[col] = '저가'
            elif col_lower == 'close':
                rename_map[col] = '종가'
            elif col_lower == 'volume':
                rename_map[col] = '거래량'
                
        df_stacked.rename(columns=rename_map, inplace=True)
        
        required_cols = ['날짜', 'yf_ticker', '시가', '고가', '저가', '종가', '거래량']
        df_stacked = df_stacked[[c for c in required_cols if c in df_stacked.columns]]
        
        df_stacked['종목코드'] = df_stacked['yf_ticker'].map(ticker_map_reverse)
        df_stacked.dropna(subset=['종목코드', '종가'], inplace=True)
        
        df_stacked['날짜'] = pd.to_datetime(df_stacked['날짜'])
        df_stacked['시가'] = pd.to_numeric(df_stacked['시가'], errors='coerce').fillna(0).astype(float).astype(int)
        df_stacked['고가'] = pd.to_numeric(df_stacked['고가'], errors='coerce').fillna(0).astype(float).astype(int)
        df_stacked['저가'] = pd.to_numeric(df_stacked['저가'], errors='coerce').fillna(0).astype(float).astype(int)
        df_stacked['종가'] = pd.to_numeric(df_stacked['종가'], errors='coerce').fillna(0).astype(float).astype(int)
        df_stacked['거래량'] = pd.to_numeric(df_stacked['거래량'], errors='coerce').fillna(0).astype(float).astype('int64')
        
        return df_stacked[['날짜', '종목코드', '시가', '고가', '저가', '종가', '거래량']]
    except Exception as e:
        print(f"[WARN] 청크 데이터 파싱 오류: {e}")
        return pd.DataFrame()

def update_and_get_data():
    today = datetime.today().strftime("%Y%m%d")
    start_date_limit = (datetime.today() - timedelta(days=150)).strftime("%Y%m%d")

    df_local = pd.DataFrame()
    last_saved_date = None

    # 1. 로컬에 기존 데이터 파일이 있는지 확인
    if os.path.exists(DB_FILE):
        print(f"기존 데이터 파일({DB_FILE})을 로드합니다.")
        try:
            df_local = pd.read_csv(
                DB_FILE, dtype={"종목코드": str}, parse_dates=["날짜"]
            )
            if not df_local.empty:
                last_saved_date = df_local["날짜"].max().strftime("%Y%m%d")
                min_saved_date = df_local["날짜"].min().strftime("%Y%m%d")
                if min_saved_date > start_date_limit:
                    print("[INFO] 로컬 데이터가 150일 미만으로 존재하므로 새로 수집을 유도합니다.")
                    df_local = pd.DataFrame()
                    last_saved_date = None
        except Exception as e:
            print(f"파일을 읽는 중 오류 발생, 새로 수집합니다: {e}")
            df_local = pd.DataFrame()

    # 2. 실제 마켓 영업일 기준 수집해야 할 날짜 계산
    if last_saved_date is not None:
        # 야후 파이낸스 등의 데이터 정산 보정을 고려하여, 로컬에 저장된 마지막 날짜의 '직전 영업일'부터 수집을 수행하여 최신화합니다.
        temp_all_days = get_market_business_days(start_date_limit, today)
        if last_saved_date in temp_all_days:
            idx = temp_all_days.index(last_saved_date)
            query_start = temp_all_days[max(0, idx - 1)]
        else:
            query_start = last_saved_date
    else:
        query_start = start_date_limit

    print(f"[PROCESS] {query_start} ~ {today} 기간의 영업일 정보를 확인 중...")
    all_business_days = get_market_business_days(query_start, today)
    target_days = all_business_days

    if not target_days:
        print("이미 최신 데이터가 반영되어 있습니다.")
        return df_local

    print(f"수집 대상 영업일 수: {len(target_days)}일 ({target_days[0]} ~ {target_days[-1]})")

    # 3. yfinance 병렬 다운로드 (종목들을 chunks로 쪼개서 다운로드)
    try:
        df_krx = fdr.StockListing('KRX')
        df_krx = df_krx[df_krx['Market'].str.contains('KOSPI|KOSDAQ', case=False, na=False)].copy()
    except Exception as e:
        print(f"[ERROR] KRX 종목 목록 로드 실패: {e}")
        return df_local

    # yfinance 티커 맵 빌드
    ticker_map = {}
    ticker_map_reverse = {}
    for _, row in df_krx.iterrows():
        code = str(row['Code']).strip().zfill(6)
        market = str(row['Market']).upper()
        yf_ticker = f"{code}.KS" if 'KOSPI' in market else f"{code}.KQ"
        ticker_map[code] = yf_ticker
        ticker_map_reverse[yf_ticker] = code

    tickers_list = list(ticker_map.values())
    chunk_size = 150
    chunks = [tickers_list[i:i + chunk_size] for i in range(0, len(tickers_list), chunk_size)]
    
    # query_start ~ today 범위를 yfinance 형식에 맞춰서 변환
    start_dt = datetime.strptime(query_start, "%Y%m%d").strftime("%Y-%m-%d")
    end_dt = (datetime.strptime(target_days[-1], "%Y%m%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"[PROCESS] 전종목(총 {len(tickers_list)}개)의 {start_dt} ~ {datetime.strptime(target_days[-1], '%Y%m%d').strftime('%Y-%m-%d')} 기간 데이터를 야후 파이낸스에서 다운로드합니다.")

    new_data_list = []
    total_chunks = len(chunks)

    # download worker function
    def download_chunk(chunk):
        try:
            df_chunk = yf.download(chunk, start=start_dt, end=end_dt, group_by='ticker', progress=False)
            parsed_df = parse_yfinance_chunk(df_chunk, ticker_map_reverse)
            return parsed_df
        except Exception as e:
            return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download_chunk, chunk): chunk for chunk in chunks}
        for future in tqdm(as_completed(futures), total=total_chunks, desc="야후 파이낸스 데이터 동기화 중"):
            df_res = future.result()
            if not df_res.empty:
                new_data_list.append(df_res)
            time.sleep(0.1)

    # 4. 기존 데이터와 신규 데이터 병합 후 파일 저장
    if new_data_list:
        df_new = pd.concat(new_data_list, ignore_index=True)
        # yfinance 데이터 날짜 필터링 (target_days 범위에 들어오는지 재검증)
        target_dates = pd.to_datetime(target_days)
        df_new = df_new[df_new['날짜'].isin(target_dates)]

        if not df_local.empty:
            df_total = pd.concat([df_local, df_new], ignore_index=True)
            df_total = df_total.drop_duplicates(
                subset=["날짜", "종목코드"], keep="last"
            )
        else:
            df_total = df_new

        # 데이터 정렬 및 저장
        df_total = df_total.sort_values(by=["종목코드", "날짜"]).reset_index(drop=True)
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        df_total.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
        print(f"로컬 파일 데이터 업데이트 완료: {DB_FILE} (총 {len(df_total)} 행)")
        return df_total
    else:
        return df_local

def screen_60day_high(df_total):
    print("60일 신고가 종목을 분석 중입니다...")
    high_new_stocks = []

    # 종목별로 그룹화
    grouped = df_total.groupby("종목코드")

    for ticker, group in grouped:
        # 최근 60거래일 데이터 확보
        df_recent = group.tail(60)

        # 1. 최소 60거래일 데이터가 다 채워져 있는지 확인
        if len(df_recent) < 60:
            continue

        # 오늘 종가와 직전 59거래일 최고 종가 분리 (종가 기준)
        today_close = df_recent["종가"].iloc[-1]
        max_close_past = df_recent["종가"].iloc[:-1].max()
        
        # '날짜'가 인덱스가 아닌 일반 컬럼이므로 idxmax()로 인덱스를 구한 뒤 '날짜' 값 추출
        high_idx = df_recent["종가"].iloc[:-1].idxmax()
        high_date = pd.to_datetime(df_recent.loc[high_idx, "날짜"])

        # 2. 오늘 거래량이 0 이하라면 거래정지 종목이므로 필터링
        today_volume = df_recent["거래량"].iloc[-1]
        if pd.isna(today_volume) or today_volume <= 0:
            continue

        # 3. 과거 최고가가 정상적이지 않은 경우 제외
        if pd.isna(max_close_past) or max_close_past <= 0:
            continue

        # 4. 오늘 종가가 과거 최고 종가보다 크거나 같을 때만 추가
        if today_close >= max_close_past:
            # 전일 종가
            prev_close = df_recent["종가"].iloc[-2]
            
            # 대비 및 등락률
            change = today_close - prev_close
            change_ratio = (change / prev_close) * 100 if prev_close != 0 else 0
            
            high_date_str = high_date.strftime('%Y-%m-%d') if not pd.isna(high_date) else 'N/A'
            
            # 파이썬 정밀 연산 및 int 캐스팅으로 int32 오버플로우 방지
            trade_amount = int(int(today_close) * int(today_volume))
            
            high_new_stocks.append(
                {
                    "종목코드": str(ticker).strip().zfill(6),
                    "당일종가": int(today_close),
                    "대비": int(change),
                    "등락률": round(change_ratio, 2),
                    "종료일 거래량": int(today_volume),
                    "종료일 거래금액": trade_amount,
                    "기존최고가": int(max_close_past),
                    "기존최고가달성일": high_date_str
                }
            )

    df_res = pd.DataFrame(high_new_stocks)
    if df_res.empty:
        return df_res

    # --- 정보 결합 시작 (KRX 목록 및 KIND 섹터) ---
    try:
        df_krx = fdr.StockListing('KRX')
        df_krx = df_krx[['Code', 'Name', 'Market', 'Stocks']].copy()
        df_krx.rename(columns={'Code': '종목코드', 'Name': '종목명', 'Market': '시장구분', 'Stocks': '상장주식수'}, inplace=True)
        df_krx['종목코드'] = df_krx['종목코드'].astype(str).str.strip().str.zfill(6)
    except Exception as e:
        print(f"[WARN] fdr 종목 리스트 로드 실패: {e}")
        df_krx = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수'])

    # KIND 섹터 데이터 가져오기
    print("[PROCESS] KIND에서 섹터 정보를 결합하는 중...")
    url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
    df_kind = pd.DataFrame()
    try:
        df_kind = pd.read_html(url, header=0, encoding='EUC-KR', flavor='lxml')[0]
    except Exception:
        try:
            import requests
            import io
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers)
            res.encoding = 'EUC-KR'
            df_kind = pd.read_html(io.StringIO(res.text), header=0, flavor='lxml')[0]
        except Exception as e:
            print(f"[WARN] KIND 크롤링 실패: {e}")

    if not df_kind.empty:
        df_kind_sub = df_kind[['종목코드', '업종', '주요제품']].copy()
        df_kind_sub['종목코드'] = df_kind_sub['종목코드'].astype(str).str.strip().str.zfill(6)
        df_kind_sub.rename(columns={'업종': '섹터A', '주요제품': '섹터B'}, inplace=True)
    else:
        df_kind_sub = pd.DataFrame(columns=['종목코드', '섹터A', '섹터B'])

    df_res['종목코드'] = df_res['종목코드'].astype(str).str.strip().str.zfill(6)
    
    # 조인
    df_merged = pd.merge(df_res, df_krx, on='종목코드', how='left')
    df_merged = pd.merge(df_merged, df_kind_sub, on='종목코드', how='left')

    # 우선주 등 미매핑 종목에 대해 본주(끝자리 0) 기준으로 섹터 재매핑
    missing_mask = df_merged['섹터A'].isna() | (df_merged['섹터A'] == '')
    if missing_mask.any() and not df_kind_sub.empty:
        df_merged.loc[missing_mask, '본주코드'] = df_merged.loc[missing_mask, '종목코드'].str[:-1] + '0'
        df_merged = pd.merge(df_merged, df_kind_sub, left_on='본주코드', right_on='종목코드', how='left', suffixes=('', '_본주'))
        
        df_merged.loc[missing_mask, '섹터A'] = df_merged.loc[missing_mask, '섹터A_본주']
        df_merged.loc[missing_mask, '섹터B'] = df_merged.loc[missing_mask, '섹터B_본주']
        df_merged.drop(columns=['본주코드', '종목코드_본주', '섹터A_본주', '섹터B_본주'], inplace=True, errors='ignore')

    df_merged['종목명'] = df_merged['종목명'].fillna('')
    df_merged = df_merged[df_merged['종목명'].str.strip() != '']
    
    df_merged['섹터A'] = df_merged['섹터A'].fillna('')
    df_merged['섹터B'] = df_merged['섹터B'].fillna('')
    df_merged['시장구분'] = df_merged['시장구분'].fillna('')

    # 추가 수치 연산 (시가총액 = 당일종가 * 상장주식수)
    df_merged['상장주식수'] = pd.to_numeric(df_merged['상장주식수'], errors='coerce').fillna(0)
    market_caps = (df_merged['당일종가'].astype(float) * df_merged['상장주식수'].astype(float)).astype('int64')
    df_merged['종료일 시가총액(억원)'] = (market_caps // 100_000_000).apply(lambda x: f"{x:,}")
    df_merged['종료일 거래금액(백만원)'] = (df_merged['종료일 거래금액'].astype('int64') // 1_000_000).apply(lambda x: f"{x:,}")
    
    comma_cols = ['기존최고가', '당일종가', '대비', '종료일 거래량']
    for col in comma_cols:
        df_merged[col] = df_merged[col].astype('int64').apply(lambda x: f"{x:,}")

    df_merged['시장구분'] = df_merged['시장구분'].str.lower()

    df_merged = df_merged.sort_values(
        by=['시장구분', '섹터A', '섹터B'],
        ascending=[False, True, True]
    )

    ordered_cols = [
        '섹터A', '섹터B', '종목코드', '종목명', '시장구분', 
        '기존최고가달성일', '기존최고가', '당일종가', '대비', '등락률', 
        '종료일 거래량', '종료일 거래금액(백만원)', '종료일 시가총액(억원)'
    ]
    
    existing_cols = [col for col in ordered_cols if col in df_merged.columns]
    return df_merged[existing_cols]

if __name__ == "__main__":
    # 1단계: 데이터 업데이트 (야후 파이낸스 병렬 다운로드 방식을 통한 동기화)
    total_data = update_and_get_data()

    # 특정 기준일(예: 2026-06-03)을 지정하여 그 날짜 기준으로 분석하려면 아래 변수에 날짜를 기입하세요.
    # None으로 설정하면 오늘 실시간 데이터를 포함한 최신 영업일 기준 데이터로 분석합니다.
    TARGET_DATE = None  # 예: "2026-06-03"

    if TARGET_DATE is not None:
        total_data = total_data[total_data["날짜"] <= pd.to_datetime(TARGET_DATE)]
        print(f"\n[INFO] {TARGET_DATE} 이전 데이터만 필터링하여 분석을 진행합니다.")

    # 2단계: 로컬 데이터를 기반으로 실시간 신고가 연산
    if TARGET_DATE is not None:
        target_dates = [pd.to_datetime(TARGET_DATE)]
    else:
        # 데이터 정산 보정이 완료된 직전 영업일과 당일 모두 결과 파일을 갱신하도록 최근 2개 영업일을 대상으로 지정합니다.
        unique_dates = sorted(total_data["날짜"].unique())
        target_dates = unique_dates[-2:] if len(unique_dates) >= 2 else unique_dates

    output_dir = os.path.join(BASE_DIR, "result", "60day_high")
    os.makedirs(output_dir, exist_ok=True)

    for t_date in target_dates:
        t_date_str = t_date.strftime("%Y%m%d")
        # 해당 분석 대상일 이전 데이터만 슬라이싱하여 그 날짜 기준으로 신고가를 집계
        df_sub = total_data[total_data["날짜"] <= t_date]
        result = screen_60day_high(df_sub)
        
        file_path = os.path.join(output_dir, f"{t_date_str}_yf.csv")
        
        if not result.empty:
            print(f"\n★ 60일 신고가 경신 종목 - {t_date.strftime('%Y-%m-%d')} (총 {len(result)}개) ★")
            print(result.to_string(index=False))
            result.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"'{file_path}' 파일로 저장 완료되었습니다.")
        else:
            # 기존에 결과물이 있었으나 수정되어 비게 된 경우를 대비해 빈 CSV로 덮어씁니다.
            result.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"\n{t_date.strftime('%Y-%m-%d')} 기준 60일 신고가를 경신한 종목이 없어 빈 파일로 저장했습니다.")
