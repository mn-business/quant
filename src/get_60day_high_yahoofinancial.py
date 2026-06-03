import os
import sys
import datetime
import pandas as pd

# Windows 콘솔 한글 깨짐 및 UTF-8 출력 보정
if sys.platform.startswith('win'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def install_and_import(module_name, package_name=None):
    import importlib
    if package_name is None:
        package_name = module_name
    try:
        importlib.import_module(module_name)
    except ImportError:
        import subprocess
        print(f"Installing {package_name}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])

# 필수 라이브러리 임포트
install_and_import("FinanceDataReader", "finance-datareader")
install_and_import("yfinance")
install_and_import("openpyxl")
install_and_import("html5lib")

import FinanceDataReader as fdr
import yfinance as yf

# src/ 하위에 위치하므로 프로젝트 루트는 이 파일의 2단계 상위
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_krx_60day_high_stocks():
    print("[INFO] KRX 보안 서버 우회를 위해 야후 파이낸스에서 전종목 가격 데이터를 분석하는 중...")
    
    # 1. KRX 전종목 목록 및 상장주식수 가져기
    try:
        df_krx = fdr.StockListing('KRX')
    except Exception as e:
        print(f"[ERROR] KRX 종목 목록 로드 실패: {e}")
        return None
        
    df_stocks = df_krx[['Code', 'Name', 'Market', 'Stocks']].copy()
    df_stocks.rename(columns={'Code': '종목코드', 'Name': '종목명', 'Market': '시장구분', 'Stocks': '상장주식수'}, inplace=True)
    df_stocks['종목코드'] = df_stocks['종목코드'].astype(str).str.zfill(6)
    
    # 2. 야후 파이낸스 티커 리스트 생성
    def get_yf_ticker(row):
        code = row['종목코드']
        market = row['시장구분']
        if 'KOSPI' in market:
            return f"{code}.KS"
        elif 'KOSDAQ' in market:
            return f"{code}.KQ"
        else:
            return f"{code}.KS"
            
    df_stocks['yf_ticker'] = df_stocks.apply(get_yf_ticker, axis=1)
    tickers = df_stocks['yf_ticker'].tolist()
    
    # 3. 100개씩 청크 단위로 나누어 병렬 다운로드 (ThreadPoolExecutor 사용)
    chunk_size = 100
    chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]
    total = len(tickers)
    
    import contextlib
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def download_chunk(idx, chunk):
        """단일 청크를 야후 파이낸스에서 다운로드하는 함수 (병렬 실행 단위)"""
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stderr(devnull):
                try:
                    df_chunk = yf.download(chunk, period="60d", progress=False)
                    if not df_chunk.empty:
                        return idx, df_chunk['High'], df_chunk['Close'], df_chunk['Volume']
                except Exception:
                    pass
        return idx, None, None, None
    
    print(f"[PROCESS] 전종목(총 {total}개)의 60영업일치 주가 및 거래량 데이터를 병렬(8스레드)로 수집 중...")
    chunk_results = {}  # 순서 유지를 위해 index 기반 dict로 결과 수집
    completed_count = 0
    
    # max_workers=8: 동시에 8개 청크를 병렬 다운로드 (야후 파이낸스 차단 방지를 위해 8 이하 권장)
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_idx = {executor.submit(download_chunk, i, chunk): i for i, chunk in enumerate(chunks)}
        for future in as_completed(future_to_idx):
            completed_count += 1
            done_tickers = min(completed_count * chunk_size, total)
            sys.stdout.write(f"   - [{done_tickers} / {total}] 완료 ({completed_count}/{len(chunks)} 청크)...\n")
            sys.stdout.flush()
            idx, h, c, v = future.result()
            if h is not None:
                chunk_results[idx] = (h, c, v)
    
    # 원래 순서대로 정렬하여 리스트에 추가
    high_dfs = []
    close_dfs = []
    volume_dfs = []
    for i in sorted(chunk_results.keys()):
        h, c, v = chunk_results[i]
        high_dfs.append(h)
        close_dfs.append(c)
        volume_dfs.append(v)
    
    if not close_dfs:
        print("[ERROR] 가격 데이터를 수집하지 못했습니다.")
        return None
        
    # 데이터 병합
    df_close = pd.concat(close_dfs, axis=1)
    df_volume = pd.concat(volume_dfs, axis=1)
    
    # 4. 60일 신고가 판별 로직 실행 (종가 기준)
    print("[PROCESS] 60일 신고가 (종가 기준) 종목 계산 중...")
    
    # 청크별 concat 시 마지막 날짜가 다를 수 있어 모든 종목이 NaN인 행을 제거
    df_close_clean = df_close.dropna(how='all')
    if df_close_clean.empty:
        print("[ERROR] 유효한 종가 데이터가 없습니다.")
        return None
    
    # 데이터프레임 전체의 최신 거래일 확보 (오늘 기준이 될 날짜)
    target_today_date = df_close_clean.index[-1]
    print(f"[INFO] 판별 기준 당일 날짜: {target_today_date.strftime('%Y-%m-%d')}")
    
    new_high_list = []
    for ticker in tickers:
        try:
            # 1. 해당 종목의 NaN이 없는 유효 가격 데이터 시계열 추출
            series = df_close[ticker].dropna()
            if len(series) < 2:
                continue
                
            # 2. 최신 거래일 및 가격 확인
            last_date = series.index[-1]
            t_close = series.iloc[-1]
            
            # [핵심] 최신 거래일이 오늘(데이터프레임 최종 날짜)과 다르면 오늘 데이터가 누락된 것이므로 제외
            if last_date != target_today_date:
                continue
                
            # 3. 어제까지의 59영업일 시계열 추출 및 최고 종가 계산
            prev_series = series.iloc[:-1]
            if prev_series.empty:
                continue
                
            c_max_prev = prev_series.max()
            high_date = prev_series.idxmax()
            
            # 등락률 계산을 위한 전일 종가
            p_close = prev_series.iloc[-1]
            
            # 오늘의 종가가 이전 59영업일 최고 종가보다 크거나 같으면 신고가 경신
            if t_close >= c_max_prev:
                change = t_close - p_close
                change_ratio = (change / p_close) * 100 if p_close != 0 else 0
                
                row_info = df_stocks[df_stocks['yf_ticker'] == ticker].iloc[0]
                
                # 최고 종가 달성일 날짜 문자열 포맷팅
                high_date_str = high_date.strftime('%Y-%m-%d') if not pd.isna(high_date) else 'N/A'
                
                # 거래량 (오늘 날짜 기준)
                t_vol = df_volume.loc[target_today_date, ticker]
                volume_val = int(t_vol) if not pd.isna(t_vol) else 0
                transaction_amount = int(t_close * volume_val)
                
                # 시가총액 계산 (오늘의 종가 * 상장주식수)
                stocks_count = row_info['상장주식수']
                market_cap = int(t_close * stocks_count) if not pd.isna(stocks_count) else 0
                
                new_high_list.append({
                    '종목코드': row_info['종목코드'],
                    '종목명': row_info['종목명'],
                    '시장구분': row_info['시장구분'],
                    '당일종가': int(t_close),
                    '대비': int(change),
                    '등락률': round(change_ratio, 2),
                    '종료일 거래량': volume_val,
                    '종료일 거래금액': transaction_amount,
                    '종료일 시가총액': market_cap,
                    '기존최고가': int(c_max_prev),
                    '기존최고가달성일': high_date_str
                })
        except Exception as e:
            continue
            
    high_df = pd.DataFrame(new_high_list)
    if high_df.empty:
        print("[ERROR] 신고가에 도달한 종목이 없습니다.")
        return None
        
    # 5. KIND에서 업종 및 주요제품 (섹터A/B) 로드 및 결합
    print("[PROCESS] KIND에서 업종 및 섹터 정보를 가져오는 중...")
    url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
    try:
        df_kind = pd.read_html(url, header=0, encoding='EUC-KR', flavor='lxml')[0]
    except Exception as e:
        print(f"[WARN] read_html 실패로 requests를 통해 가져옵니다 ({e})")
        import requests
        import io
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        res = requests.get(url, headers=headers)
        res.encoding = 'EUC-KR'
        df_kind = pd.read_html(io.StringIO(res.text), header=0, flavor='lxml')[0]
        
    df_kind_sub = df_kind[['종목코드', '업종', '주요제품']].copy()
    df_kind_sub['종목코드'] = df_kind_sub['종목코드'].astype(str).str.zfill(6)
    df_kind_sub.rename(columns={'업종': '섹터A', '주요제품': '섹터B'}, inplace=True)
    
    # 병합
    df_merged = pd.merge(high_df, df_kind_sub, on='종목코드', how='left')
    
    # 우선주 등 미매핑 종목에 대해 본주(끝자리 0) 기준으로 섹터 재매핑
    missing_mask = df_merged['섹터A'].isna() | (df_merged['섹터A'] == '')
    if missing_mask.any():
        print("   -> 우선주 등 미매핑 종목에 대해 본주(끝자리 0) 기준으로 섹터 재매핑 중...")
        df_merged.loc[missing_mask, '본주코드'] = df_merged.loc[missing_mask, '종목코드'].str[:-1] + '0'
        df_merged = pd.merge(df_merged, df_kind_sub, left_on='본주코드', right_on='종목코드', how='left', suffixes=('', '_본주'))
        
        df_merged.loc[missing_mask, '섹터A'] = df_merged.loc[missing_mask, '섹터A_본주']
        df_merged.loc[missing_mask, '섹터B'] = df_merged.loc[missing_mask, '섹터B_본주']
        
        df_merged.drop(columns=['본주코드', '종목코드_본주', '섹터A_본주', '섹터B_본주'], inplace=True, errors='ignore')
        
    df_merged['섹터A'] = df_merged['섹터A'].fillna('')
    df_merged['섹터B'] = df_merged['섹터B'].fillna('')
    
    # 등락률 순 정렬
    df_merged = df_merged.sort_values(by='등락률', ascending=False)
    
    # 컬럼 순서 재조정 (가독성을 위한 순서 배치)
    ordered_cols = [
        '종목코드', '종목명', '시장구분', '당일종가', '대비', '등락률', 
        '종료일 거래량', '종료일 거래금액', '종료일 시가총액', 
        '섹터A', '섹터B', '기존최고가', '기존최고가달성일'
    ]
    df_merged = df_merged[ordered_cols]
    
    return df_merged

if __name__ == '__main__':
    # 함수 실행
    result = get_krx_60day_high_stocks()
    
    if result is not None and not result.empty:
        print(f"\n[SUCCESS] 오늘 자 60일 신고가 경신 종목 (총 {len(result)}개 발견)")
        print("=" * 110)
        # 상위 30개만 화면에 먼저 출력
        print(result[['시장구분', '종목명', '당일종가', '등락률', '종료일 거래량', '종료일 시가총액', '기존최고가달성일']].head(30).to_string(index=False))
        print("=" * 110)
        
        # 엑셀 파일로 깔끔하게 저장 (프로젝트 루트 기준 result/ 폴더)
        result_dir = os.path.join(BASE_DIR, "result")
        os.makedirs(result_dir, exist_ok=True)
        today_file = datetime.date.today().strftime('%Y%m%d')
        filename = os.path.join(result_dir, f"KRX_60일_신고가_{today_file}.xlsx")
        result.to_excel(filename, index=False)
        print(f"[SAVE] 엑셀 파일 저장 완료: {filename}")
    else:
        print("[ERROR] 신고가에 도달한 종목이 없거나 데이터 수집에 실패했습니다.")
