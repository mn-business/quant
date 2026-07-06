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

# 데이터 보관용 로컬 CSV 파일 경로를 구하는 헬퍼 함수
def get_db_file_path(market_name):
    return os.path.join(BASE_DIR, "db", f"60day_high_{market_name.lower()}.csv")

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

def get_robust_krx_listing():
    """fdr.StockListing('KRX')가 404 에러 등으로 실패 시 GitHub 캐시에서 날짜를 역산하여 로드하는 robust한 래퍼입니다."""
    import requests
    import io
    
    # 1. fdr 직접 호출 시도
    try:
        df = fdr.StockListing('KRX')
        if not df.empty:
            return df
    except Exception as e:
        print(f"[WARN] fdr.StockListing('KRX') 직접 호출 실패 ({e}). 백업 캐시 다운로드를 시도합니다.")
    
    # 2. GitHub 캐시 데이터 역산 다운로드 시도 (최대 10일 전까지 역산)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    base_url = 'https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/krx/'
    
    for i in range(10):
        check_date = (datetime.today() - timedelta(days=i)).strftime('%Y-%m-%d')
        url = f"{base_url}{check_date}.csv"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                print(f"[INFO] GitHub KRX 캐시 데이터 로드 성공: {check_date}")
                df = pd.read_csv(io.StringIO(res.text), index_col=0, dtype={'Code': str, 'Dept': str, 'ChangeCode': str, 'MarketId': str})
                df = df.reset_index(drop=True)
                return df
        except Exception:
            continue
            
    # 3. 마지막 수단: corazzon 퍼블릭 미러
    try:
        url = "https://raw.githubusercontent.com/corazzon/finance-data-analysis/main/krx.csv"
        df = pd.read_csv(url)
        df.rename(columns={'Symbol': 'Code'}, inplace=True)
        print("[INFO] corazzon KRX 미러 데이터 로드 성공")
        return df
    except Exception as e:
        print(f"[ERROR] 모든 KRX 종목 리스트 로드 수단이 실패했습니다: {e}")
        raise e


def parse_yfinance_chunk(df_chunk, ticker_map_reverse, chunk_tickers=None):
    """yf.download 결과인 MultiIndex DataFrame을 [날짜, 종목코드, 시가, 고가, 저가, 종가, 거래량] 형태로 변환"""
    if df_chunk.empty:
        return pd.DataFrame()
    
    if not isinstance(df_chunk.columns, pd.MultiIndex):
        ticker_name = df_chunk.columns.name
        if not ticker_name and chunk_tickers:
            ticker_name = chunk_tickers[0]
        if not ticker_name:
            ticker_name = "UNKNOWN"
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
        df_stacked['시가'] = pd.to_numeric(df_stacked['시가'], errors='coerce').fillna(0).astype(float)
        df_stacked['고가'] = pd.to_numeric(df_stacked['고가'], errors='coerce').fillna(0).astype(float)
        df_stacked['저가'] = pd.to_numeric(df_stacked['저가'], errors='coerce').fillna(0).astype(float)
        df_stacked['종가'] = pd.to_numeric(df_stacked['종가'], errors='coerce').fillna(0).astype(float)
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

    # 1. 로컬에 기존 데이터 파일이 있는지 확인하여 병합 로드
    local_dfs = []
    active_markets = ['nasdaq', 'sp500', 'twse', 'sse', 'szse', 'hkex', 'tse', 'hose']
    for m in active_markets:
        db_path = get_db_file_path(m)
        if os.path.exists(db_path):
            print(f"기존 {m.upper()} 데이터 파일({db_path})을 로드합니다.")
            try:
                df_m = pd.read_csv(db_path, dtype={"종목코드": str}, parse_dates=["날짜"])
                if not df_m.empty:
                    local_dfs.append(df_m)
            except Exception as e:
                print(f"{m.upper()} 파일을 읽는 중 오류 발생: {e}")
                
    if local_dfs:
        df_local = pd.concat(local_dfs, ignore_index=True)
        if not df_local.empty:
            last_saved_date = df_local["날짜"].max().strftime("%Y%m%d")
            # 60일 신고가 계산을 위해 최소한 70영업일 이상의 데이터가 필요함
            if len(df_local["날짜"].unique()) < 70:
                print("[INFO] 로컬 데이터 영업일수가 70일 미만으로 부족하여 새로 수집을 유도합니다.")
                df_local = pd.DataFrame()
                last_saved_date = None

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
    ticker_map = {}
    ticker_map_reverse = {}
    
    # 각 시장별 심볼 셋 정의
    sp500_symbols = set()
    nasdaq_symbols = set()
    sse_symbols = set()
    szse_symbols = set()
    twse_symbols = set()
    twse_symbols.add('^TWII')
    hkex_symbols = set()
    tse_symbols = set()
    hose_symbols = set()

    # (2) 미국 S&P 500 종목 목록 로드
    try:
        df_sp500 = fdr.StockListing('S&P500')
        for _, row in df_sp500.iterrows():
            symbol = str(row['Symbol']).strip()
            sp500_symbols.add(symbol)
            yf_ticker = symbol.replace('.', '-')
            ticker_map[symbol] = yf_ticker
            ticker_map_reverse[yf_ticker] = symbol
    except Exception as e:
        print(f"[WARN] S&P500 종목 목록 로드 실패: {e}")

    # (3) 미국 NASDAQ 종목 목록 로드
    try:
        df_nasdaq = fdr.StockListing('NASDAQ')
        for _, row in df_nasdaq.iterrows():
            symbol = str(row['Symbol']).strip()
            nasdaq_symbols.add(symbol)
            yf_ticker = symbol.replace('.', '-')
            ticker_map[symbol] = yf_ticker
            ticker_map_reverse[yf_ticker] = symbol
    except Exception as e:
        print(f"[WARN] NASDAQ 종목 목록 로드 실패: {e}")

    # (3) 대만 TWSE(가권) 지수 로드
    # try:
    #     ticker_map['^TWII'] = '^TWII'
    #     ticker_map_reverse['^TWII'] = '^TWII'
    # except Exception as e:
    #     print(f"[WARN] 대만 TWSE 지수 로드 실패: {e}")

    # (4) 중국 SSE 종목 목록 로드
    try:
        df_sse = fdr.StockListing('SSE')
        for _, row in df_sse.iterrows():
            symbol = str(row['Symbol']).strip()
            sse_symbols.add(symbol)
            yf_ticker = f"{symbol}.SS"
            ticker_map[symbol] = yf_ticker
            ticker_map_reverse[yf_ticker] = symbol
    except Exception as e:
        print(f"[WARN] SSE 종목 목록 로드 실패: {e}")

    # (5) 중국 SZSE 종목 목록 로드
    try:
        df_szse = fdr.StockListing('SZSE')
        for _, row in df_szse.iterrows():
            symbol = str(row['Symbol']).strip()
            szse_symbols.add(symbol)
            yf_ticker = f"{symbol}.SZ"
            ticker_map[symbol] = yf_ticker
            ticker_map_reverse[yf_ticker] = symbol
    except Exception as e:
        print(f"[WARN] SZSE 종목 목록 로드 실패: {e}")

    # (6) 일본 TSE 종목 목록 로드
    try:
        df_tse = fdr.StockListing('TSE')
        for _, row in df_tse.iterrows():
            symbol = str(row['Symbol']).strip()
            tse_symbols.add(symbol)
            yf_ticker = f"{symbol}.T"
            ticker_map[symbol] = yf_ticker
            ticker_map_reverse[yf_ticker] = symbol
    except Exception as e:
        print(f"[WARN] TSE 종목 목록 로드 실패: {e}")

    # (7) 홍콩 HKEX 종목 목록 로드
    try:
        df_hkex = fdr.StockListing('HKEX')
        for _, row in df_hkex.iterrows():
            symbol = str(row['Symbol']).strip()
            hkex_symbols.add(symbol)
            yf_ticker = f"{int(symbol):04d}.HK"
            ticker_map[symbol] = yf_ticker
            ticker_map_reverse[yf_ticker] = symbol
    except Exception as e:
        print(f"[WARN] HKEX 종목 목록 로드 실패: {e}")

    # (8) 베트남 HOSE 종목 목록 로드
    try:
        df_hose = fdr.StockListing('HOSE')
        for _, row in df_hose.iterrows():
            symbol = str(row['Symbol']).strip()
            hose_symbols.add(symbol)
            yf_ticker = f"{symbol}.VN"
            ticker_map[symbol] = yf_ticker
            ticker_map_reverse[yf_ticker] = symbol
    except Exception as e:
        print(f"[WARN] HOSE 종목 목록 로드 실패: {e}")

    tickers_list = list(ticker_map.values())

    # 로컬 DB에 이미 60일 이상 충분한 데이터가 쌓여 있는지 판단하여 다운로드 그룹 분류
    full_download_tickers = []
    incremental_tickers = []
    
    if df_local.empty:
        full_download_tickers = tickers_list
    else:
        counts = df_local.groupby("종목코드")["날짜"].count().to_dict()
        for yf_ticker in tickers_list:
            code = ticker_map_reverse.get(yf_ticker)
            if code not in counts or counts[code] < 60:
                full_download_tickers.append(yf_ticker)
            else:
                incremental_tickers.append(yf_ticker)

    new_data_list = []
    end_dt = (datetime.strptime(target_days[-1], "%Y%m%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    # 1단계: 전체 다운로드 대상 종목들 수집 (start_dt = 150일 전부터)
    if full_download_tickers:
        start_dt_full = datetime.strptime(start_date_limit, "%Y%m%d").strftime("%Y-%m-%d")
        print(f"[PROCESS] 신규 또는 데이터가 부족한 종목 {len(full_download_tickers)}개에 대해 {start_dt_full} ~ {end_dt} 전체 수집을 시작합니다.")
        
        chunk_size = 150
        chunks_full = [full_download_tickers[i:i + chunk_size] for i in range(0, len(full_download_tickers), chunk_size)]
        
        def download_chunk_full(chunk):
            try:
                df_chunk = yf.download(chunk, start=start_dt_full, end=end_dt, group_by='ticker', progress=False, timeout=15)
                parsed_df = parse_yfinance_chunk(df_chunk, ticker_map_reverse, chunk)
                return parsed_df
            except Exception as e:
                return pd.DataFrame()
                
        with ThreadPoolExecutor(max_workers=4) as executor:  # Rate Limit 완화: 8 → 4
            futures = {executor.submit(download_chunk_full, chunk): chunk for chunk in chunks_full}
            for future in tqdm(as_completed(futures), total=len(chunks_full), desc="신규 종목 전체 수집 중"):
                df_res = future.result()
                if not df_res.empty:
                    new_data_list.append(df_res)
                time.sleep(0.1)

    # 2단계: 기존 증분 다운로드 대상 종목들 수집 (start_dt = query_start부터)
    if incremental_tickers:
        start_dt_inc = datetime.strptime(query_start, "%Y%m%d").strftime("%Y-%m-%d")
        print(f"[PROCESS] 기존 종목 {len(incremental_tickers)}개에 대해 {start_dt_inc} ~ {end_dt} 증분 수집을 시작합니다.")
        
        chunk_size = 150
        chunks_inc = [incremental_tickers[i:i + chunk_size] for i in range(0, len(incremental_tickers), chunk_size)]
        
        def download_chunk_inc(chunk):
            try:
                df_chunk = yf.download(chunk, start=start_dt_inc, end=end_dt, group_by='ticker', progress=False, timeout=15)
                parsed_df = parse_yfinance_chunk(df_chunk, ticker_map_reverse, chunk)
                return parsed_df
            except Exception as e:
                return pd.DataFrame()
                
        with ThreadPoolExecutor(max_workers=4) as executor:  # Rate Limit 완화: 8 → 4
            futures = {executor.submit(download_chunk_inc, chunk): chunk for chunk in chunks_inc}
            for future in tqdm(as_completed(futures), total=len(chunks_inc), desc="기존 종목 증분 수집 중"):
                df_res = future.result()
                if not df_res.empty:
                    new_data_list.append(df_res)
                time.sleep(0.1)

    # 4. 기존 데이터와 신규 데이터 병합 후 파일 저장
    if new_data_list:
        df_new = pd.concat(new_data_list, ignore_index=True)
        
        # 각 종목별로 알맞은 날짜 범위 필터링 (신규 전체 수집 vs 기존 증분 수집)
        full_codes = set(ticker_map_reverse[t] for t in full_download_tickers)
        
        # 1) 전체 수집 종목: start_date_limit ~ target_days[-1] 범위 유지
        df_new_full = df_new[df_new['종목코드'].isin(full_codes)].copy()
        if not df_new_full.empty:
            limit_dt = pd.to_datetime(start_date_limit)
            max_dt = pd.to_datetime(target_days[-1])
            df_new_full = df_new_full[(df_new_full['날짜'] >= limit_dt) & (df_new_full['날짜'] <= max_dt)]
            
        # 2) 증분 수집 종목: target_days 범위만 유지
        df_new_inc = df_new[~df_new['종목코드'].isin(full_codes)].copy()
        if not df_new_inc.empty:
            target_dates = pd.to_datetime(target_days)
            df_new_inc = df_new_inc[df_new_inc['날짜'].isin(target_dates)]
            
        df_new = pd.concat([df_new_full, df_new_inc], ignore_index=True)

        if not df_local.empty:
            df_total = pd.concat([df_local, df_new], ignore_index=True)
            df_total = df_total.drop_duplicates(
                subset=["날짜", "종목코드"], keep="last"
            )
        else:
            df_total = df_new

        # 데이터 정렬
        df_total = df_total.sort_values(by=["종목코드", "날짜"]).reset_index(drop=True)

        # 시장 분류 매핑용 헬퍼 함수
        def get_market_of_code(code):
            if code in sse_symbols:
                return 'sse'
            elif code in szse_symbols:
                return 'szse'
            elif code in sp500_symbols:
                return 'sp500'
            elif code in nasdaq_symbols:
                return 'nasdaq'
            elif code in twse_symbols or code == '^TWII':
                return 'twse'
            elif code in hkex_symbols:
                return 'hkex'
            elif code in tse_symbols:
                return 'tse'
            elif code in hose_symbols:
                return 'hose'
            return 'nasdaq' # 기본 Fallback

        df_total['market_tmp'] = df_total['종목코드'].apply(get_market_of_code)

        # 시장별 분할 저장 및 최근 100 영업일 Pruning 적용
        for m in active_markets:
            df_m = df_total[df_total['market_tmp'] == m].copy()
            df_m.drop(columns=['market_tmp'], errors='ignore', inplace=True)
            
            if not df_m.empty:
                # 슬라이딩 윈도우: 최근 100 영업일 분량만 보존
                unique_dates = sorted(df_m["날짜"].unique())
                if len(unique_dates) > 100:
                    cutoff_date = unique_dates[-100]
                    df_m = df_m[df_m["날짜"] >= cutoff_date]
                
                db_path = get_db_file_path(m)
                os.makedirs(os.path.dirname(db_path), exist_ok=True)
                df_m.to_csv(db_path, index=False, encoding="utf-8-sig")
                print(f"로컬 파일 데이터 업데이트 완료: {db_path} (총 {len(df_m)} 행)")

        df_total.drop(columns=['market_tmp'], errors='ignore', inplace=True)
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
            
            # 당일 최고가 및 최저가
            today_high = df_recent["고가"].iloc[-1]
            today_low = df_recent["저가"].iloc[-1]
            
            # 파이썬 정밀 연산으로 int32 오버플로우 방지
            trade_amount = float(today_close) * int(today_volume)
            
            # 종목코드가 숫자 형태인 경우에만 6자리 zfill 수행 (예: 한국 005930, 일본 7203 등)
            ticker_str = str(ticker).strip()
            if ticker_str.isdigit():
                ticker_str = ticker_str.zfill(6)
            
            # 1주 전 (5영업일 전) 및 3개월 전 (60영업일 전) 종가 상승률 계산
            close_1w = group["종가"].iloc[-6] if len(group) >= 6 else 0.0
            rate_1w = round(((today_close - close_1w) / close_1w) * 100, 2) if close_1w != 0.0 else 0.0

            close_3m = group["종가"].iloc[-61] if len(group) >= 61 else (group["종가"].iloc[0] if len(group) > 0 else 0.0)
            rate_3m = round(((today_close - close_3m) / close_3m) * 100, 2) if close_3m != 0.0 else 0.0
            
            high_new_stocks.append(
                {
                    "종목코드": ticker_str,
                    "당일최고가": float(today_high),
                    "당일최저가": float(today_low),
                    "당일종가": float(today_close),
                    "3개월 종가 상승률": f"{rate_3m:+.2f}%",
                    "1주 종가 상승률": f"{rate_1w:+.2f}%",
                    "대비": float(change),
                    "등락률": round(change_ratio, 2),
                    "종료일 거래량": int(today_volume),
                    "종료일 거래금액": trade_amount,
                    "기존최고가": float(max_close_past),
                    "기존최고가달성일": high_date_str
                }
            )

    df_res = pd.DataFrame(high_new_stocks)
    if df_res.empty:
        return df_res

    # --- 정보 결합 시작 (KRX, S&P500, TSE 목록 및 KIND 섹터) ---
    # 1. 한국 KRX 및 KIND 정보 구축
    try:
        df_krx = get_robust_krx_listing()
        df_krx = df_krx[['Code', 'Name', 'Market', 'Stocks']].copy()
        df_krx.rename(columns={'Code': '종목코드', 'Name': '종목명', 'Market': '시장구분', 'Stocks': '상장주식수'}, inplace=True)
        df_krx['종목코드'] = df_krx['종목코드'].astype(str).str.strip().str.zfill(6)
    except Exception as e:
        print(f"[WARN] fdr KRX 종목 리스트 로드 실패: {e}")
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

    df_krx_merged = pd.merge(df_krx, df_kind_sub, on='종목코드', how='left')
    # 본주 기준 섹터 재매핑
    missing_mask = df_krx_merged['섹터A'].isna() | (df_krx_merged['섹터A'] == '')
    if missing_mask.any() and not df_kind_sub.empty:
        df_krx_merged.loc[missing_mask, '본주코드'] = df_krx_merged.loc[missing_mask, '종목코드'].str[:-1] + '0'
        df_krx_merged = pd.merge(df_krx_merged, df_kind_sub, left_on='본주코드', right_on='종목코드', how='left', suffixes=('', '_본주'))
        df_krx_merged = df_krx_merged.reset_index(drop=True)
        
        # merge 이후 인덱스가 재설정되므로 missing_mask를 새로 계산
        missing_mask = df_krx_merged['섹터A'].isna() | (df_krx_merged['섹터A'] == '')
        df_krx_merged.loc[missing_mask, '섹터A'] = df_krx_merged.loc[missing_mask, '섹터A_본주']
        df_krx_merged.loc[missing_mask, '섹터B'] = df_krx_merged.loc[missing_mask, '섹터B_본주']
        df_krx_merged.drop(columns=['본주코드', '종목코드_본주', '섹터A_본주', '섹터B_본주'], inplace=True, errors='ignore')

    # 2. 미국 S&P 500 & NASDAQ 정보 구축
    df_us_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
    
    df_sp500_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
    try:
        df_sp500 = fdr.StockListing('S&P500')
        df_sp500_meta = pd.DataFrame({
            '종목코드': df_sp500['Symbol'].astype(str).str.strip(),
            '종목명': df_sp500['Name'],
            '시장구분': 'S&P500',
            '상장주식수': 0,
            '섹터A': df_sp500['Sector'].fillna(''),
            '섹터B': df_sp500['Industry'].fillna('')
        })
    except Exception as e:
        print(f"[WARN] fdr S&P500 메타 정보 로드 실패: {e}")

    df_nasdaq_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
    try:
        df_nasdaq = fdr.StockListing('NASDAQ')
        df_nasdaq_meta = pd.DataFrame({
            '종목코드': df_nasdaq['Symbol'].astype(str).str.strip(),
            '종목명': df_nasdaq['Name'],
            '시장구분': 'NASDAQ',
            '상장주식수': 0,
            '섹터A': df_nasdaq['Industry'].fillna(''),
            '섹터B': df_nasdaq['IndustryCode'].fillna('') if 'IndustryCode' in df_nasdaq.columns else ''
        })
    except Exception as e:
        print(f"[WARN] fdr NASDAQ 메타 정보 로드 실패: {e}")

    df_us_meta = pd.concat([df_sp500_meta, df_nasdaq_meta], ignore_index=True)

    # 3. 대만 TWSE 정보 구축
    try:
        df_tw_meta = pd.DataFrame([{
            '종목코드': '^TWII',
            '종목명': '대만 가권지수',
            '시장구분': 'TWSE',
            '상장주식수': 0,
            '섹터A': '지수',
            '섹터B': '대만'
        }])
    except Exception as e:
        print(f"[WARN] 대만 TWSE 메타 정보 구축 실패: {e}")

    # 4. 중국 SSE 정보 구축
    df_sse_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
    try:
        df_sse = fdr.StockListing('SSE')
        df_sse_meta = pd.DataFrame({
            '종목코드': df_sse['Symbol'].astype(str).str.strip(),
            '종목명': df_sse['Name'],
            '시장구분': 'SSE',
            '상장주식수': 0,
            '섹터A': df_sse['Industry'].fillna('') if 'Industry' in df_sse.columns else '',
            '섹터B': df_sse['IndustryCode'].fillna('') if 'IndustryCode' in df_sse.columns else ''
        })
    except Exception as e:
        print(f"[WARN] fdr SSE 메타 정보 로드 실패: {e}")

    # 5. 중국 SZSE 정보 구축
    df_szse_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
    try:
        df_szse = fdr.StockListing('SZSE')
        df_szse_meta = pd.DataFrame({
            '종목코드': df_szse['Symbol'].astype(str).str.strip(),
            '종목명': df_szse['Name'],
            '시장구분': 'SZSE',
            '상장주식수': 0,
            '섹터A': df_szse['Industry'].fillna('') if 'Industry' in df_szse.columns else '',
            '섹터B': df_szse['IndustryCode'].fillna('') if 'IndustryCode' in df_szse.columns else ''
        })
    except Exception as e:
        print(f"[WARN] fdr SZSE 메타 정보 로드 실패: {e}")

    # 6. 일본 TSE 정보 구축
    df_tse_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
    try:
        df_tse = fdr.StockListing('TSE')
        df_tse_meta = pd.DataFrame({
            '종목코드': df_tse['Symbol'].astype(str).str.strip(),
            '종목명': df_tse['Name'],
            '시장구분': 'TSE',
            '상장주식수': 0,
            '섹터A': df_tse['Industry'].fillna('') if 'Industry' in df_tse.columns else '',
            '섹터B': df_tse['IndustryCode'].fillna('') if 'IndustryCode' in df_tse.columns else ''
        })
    except Exception as e:
        print(f"[WARN] fdr TSE 메타 정보 로드 실패: {e}")

    # 7. 홍콩 HKEX 정보 구축
    df_hkex_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
    try:
        df_hkex = fdr.StockListing('HKEX')
        df_hkex_meta = pd.DataFrame({
            '종목코드': df_hkex['Symbol'].astype(str).str.strip(),
            '종목명': df_hkex['Name'],
            '시장구분': 'HKEX',
            '상장주식수': 0,
            '섹터A': df_hkex['Industry'].fillna('') if 'Industry' in df_hkex.columns else '',
            '섹터B': df_hkex['IndustryCode'].fillna('') if 'IndustryCode' in df_hkex.columns else ''
        })
    except Exception as e:
        print(f"[WARN] fdr HKEX 메타 정보 로드 실패: {e}")

    # 8. 베트남 HOSE 정보 구축
    df_hose_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
    try:
        df_hose = fdr.StockListing('HOSE')
        df_hose_meta = pd.DataFrame({
            '종목코드': df_hose['Symbol'].astype(str).str.strip(),
            '종목명': df_hose['Name'],
            '시장구분': 'HOSE',
            '상장주식수': 0,
            '섹터A': df_hose['Industry'].fillna('') if 'Industry' in df_hose.columns else '',
            '섹터B': df_hose['IndustryCode'].fillna('') if 'IndustryCode' in df_hose.columns else ''
        })
    except Exception as e:
        print(f"[WARN] fdr HOSE 메타 정보 로드 실패: {e}")

    # 모든 메타 정보 수직 결합
    df_unified_meta = pd.concat([
        df_krx_merged, df_us_meta, df_tw_meta, df_sse_meta, df_szse_meta, 
        df_tse_meta, df_hkex_meta, df_hose_meta
    ], ignore_index=True)

    df_res['종목코드'] = df_res['종목코드'].astype(str).str.strip()
    df_unified_meta['종목코드'] = df_unified_meta['종목코드'].astype(str).str.strip()
    
    # 조인
    df_merged = pd.merge(df_res, df_unified_meta, on='종목코드', how='left')

    df_merged['종목명'] = df_merged['종목명'].fillna('')
    df_merged = df_merged[df_merged['종목명'].str.strip() != '']
    
    df_merged['섹터A'] = df_merged['섹터A'].fillna('')
    df_merged['섹터B'] = df_merged['섹터B'].fillna('')
    df_merged['시장구분'] = df_merged['시장구분'].fillna('')

    # 추가 수치 연산 (시가총액 = 당일종가 * 상장주식수)
    df_merged['상장주식수'] = pd.to_numeric(df_merged['상장주식수'], errors='coerce').fillna(0)
    market_caps = (df_merged['당일종가'].astype(float) * df_merged['상장주식수'].astype(float)).astype('int64')
    
    # 시가총액 포맷팅: 상장주식수가 0인 미국/일본 주식은 'N/A'로 표시
    df_merged['종료일 시가총액(억원)'] = market_caps.apply(lambda x: f"{x // 100_000_000:,}" if x > 0 else 'N/A')
    
    # 종료일 거래금액 포맷팅: 환산하지 않고 통화 단위 그대로 백만 단위 표시
    df_merged['종료일 거래금액(백만원)'] = df_merged.apply(
        lambda r: f"{int(r['종료일 거래금액'] // 1_000_000):,}" if str(r['시장구분']).upper() in ['KOSPI', 'KOSDAQ']
        else f"{r['종료일 거래금액'] / 1_000_000:,.2f}" if str(r['시장구분']).upper() in ['NASDAQ', 'S&P500']
        else f"{int(r['종료일 거래금액'] // 1_000_000):,}", axis=1
    )

    # 가격/대비/거래량 콤마 포맷팅
    def format_row_value(r, col):
        val = r[col]
        market = str(r['시장구분']).upper()
        if market in ['KOSPI', 'KOSDAQ']:
            return f"{int(round(val)):,}"
        elif market in ['NASDAQ', 'S&P500']:
            return f"{val:,.2f}"
        else: # Japan TSE 등
            if val == int(val):
                return f"{int(val):,}"
            else:
                return f"{val:,.2f}"

    for col in ['당일최고가', '당일최저가', '당일종가', '대비', '기존최고가']:
        df_merged[col] = df_merged.apply(lambda r: format_row_value(r, col), axis=1)

    df_merged['종료일 거래량'] = df_merged['종료일 거래량'].astype('int64').apply(lambda x: f"{x:,}")
    df_merged['시장구분'] = df_merged['시장구분'].str.lower()

    df_merged = df_merged.sort_values(
        by=['시장구분', '섹터A', '섹터B'],
        ascending=[False, True, True]
    )

    ordered_cols = [
        '섹터A', '섹터B', '종목코드', '종목명', '시장구분', 
        '기존최고가달성일', '기존최고가', '당일최고가', '당일최저가', '당일종가', 
        '3개월 종가 상승률', '1주 종가 상승률', '대비', '등락률', 
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
        month_str = t_date.strftime("%Y%m")
        monthly_output_dir = os.path.join(output_dir, month_str)
        os.makedirs(monthly_output_dir, exist_ok=True)
        
        # 해당 분석 대상일 이전 데이터만 슬라이싱하여 그 날짜 기준으로 신고가를 집계
        df_sub = total_data[total_data["날짜"] <= t_date]
        result = screen_60day_high(df_sub)
        
        # 시장별 분리 처리 매핑 정의
        markets_mapping = {
            # "krx": result[result['시장구분'].isin(['kospi', 'kosdaq'])],
            "sp500": result[result['시장구분'] == 's&p500'],
            "nasdaq": result[result['시장구분'] == 'nasdaq'],
            # "twse": result[result['시장구분'] == 'twse'],
            "sse": result[result['시장구분'] == 'sse'],
            "szse": result[result['시장구분'] == 'szse'],
            "tse": result[result['시장구분'] == 'tse'],
            "hkex": result[result['시장구분'] == 'hkex'],
            "hose": result[result['시장구분'] == 'hose'],
        }
        
        for m_name, df_m in markets_mapping.items():
            file_path = os.path.join(monthly_output_dir, f"{t_date_str}_yf_{m_name}.csv")
            
            if not df_m.empty:
                print(f"\n★ 60일 신고가 경신 종목 [{m_name.upper()}] - {t_date.strftime('%Y-%m-%d')} (총 {len(df_m)}개) ★")
                print(df_m.to_string(index=False))
                df_m.to_csv(file_path, index=False, encoding="utf-8-sig")
                print(f"'{file_path}' 파일로 저장 완료되었습니다.")
            else:
                # 기존에 결과물이 있었으나 수정되어 비게 된 경우를 대비해 빈 CSV로 덮어씁니다.
                df_m.to_csv(file_path, index=False, encoding="utf-8-sig")
                print(f"{t_date.strftime('%Y-%m-%d')} 기준 [{m_name.upper()}] 60일 신고가를 경신한 종목이 없어 빈 파일로 저장했습니다.")
