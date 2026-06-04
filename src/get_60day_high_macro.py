from datetime import datetime, timedelta
import os
import time
import pandas as pd
import yfinance as yf

# 스크립트 위치 기준 상위 루트 디렉토리 구하기
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 1. 대상 매크로 지표 정의 (티커: (이름, 구분))
MACRO_TICKERS = {
    "^KS11": ("코스피 지수", "주요지수"),
    "^KQ11": ("코스닥 지수", "주요지수"),
    "^GSPC": ("S&P 500", "주요지수"),
    "^IXIC": ("나스닥 종합", "주요지수"),
    "^SOX": ("필라델피아 반도체", "주요지수"),
    "^N225": ("니케이 225", "주요지수"),
    "USDKRW=X": ("원/달러 환율", "환율"),
    "DX-Y.NYB": ("달러 인덱스", "환율"),
    "GC=F": ("금 선물", "원자재"),
    "CL=F": ("WTI 유가", "원자재"),
    "^TNX": ("미국 10년물 국채금리", "채권금리"),
}

def get_market_business_days(start_date, end_date):
    """삼성전자(005930.KS) 데이터를 기준으로 실제 주식시장 영업일 목록을 가져옵니다."""
    try:
        start_dt = datetime.strptime(start_date, "%Y%m%d").strftime("%Y-%m-%d")
        end_dt = (datetime.strptime(end_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        df = yf.download("005930.KS", start=start_dt, end=end_dt, progress=False)
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.droplevel(1)
        return df.index.strftime("%Y%m%d").tolist()
    except Exception as e:
        print(f"[WARN] 영업일 목록 조회 실패: {e}")
        s = datetime.strptime(start_date, "%Y%m%d")
        e = datetime.strptime(end_date, "%Y%m%d")
        delta = e - s
        all_days = [(s + timedelta(days=i)).strftime("%Y%m%d") for i in range(delta.days + 1)]
        business_days = [d for d in all_days if datetime.strptime(d, "%Y%m%d").weekday() < 5]
        return business_days

def run_macro_screener(target_date):
    print(f"\n[PROCESS] {target_date.strftime('%Y-%m-%d')} 기준 글로벌 매크로 지표 분석 중...")
    
    # 60일 신고가 계산을 위해 여유 있게 200일 이전부터의 데이터를 로드
    start_dt = (target_date - timedelta(days=200)).strftime("%Y-%m-%d")
    end_dt = (target_date + timedelta(days=5)).strftime("%Y-%m-%d") # 넉넉하게 다음 날까지 다운로드
    
    tickers = list(MACRO_TICKERS.keys())
    try:
        # 일괄 다운로드
        df = yf.download(tickers, start=start_dt, end=end_dt, group_by='ticker', progress=False)
    except Exception as e:
        print(f"[ERROR] 야후 파이낸스 데이터 다운로드 실패: {e}")
        return pd.DataFrame()
        
    high_new_macros = []
    
    for ticker, (name, category) in MACRO_TICKERS.items():
        # 데이터 유효성 검사
        if df.empty or ticker not in df.columns.levels[0]:
            continue
            
        df_ticker = df[ticker].dropna(subset=['Close']).copy()
        
        # 분석 대상일(target_date) 이하의 데이터만 필터링
        df_ticker = df_ticker[df_ticker.index <= target_date]
        
        if len(df_ticker) < 60:
            continue
            
        df_recent = df_ticker.tail(60)
        
        today_close = df_recent["Close"].iloc[-1]
        max_close_past = df_recent["Close"].iloc[:-1].max()
        high_idx = df_recent["Close"].iloc[:-1].idxmax()
        high_date = pd.to_datetime(high_idx)
        
        today_close = float(today_close)
        max_close_past = float(max_close_past)
        
        # 오늘 종가가 과거 최고 종가보다 크거나 같을 때만 추가
        if today_close >= max_close_past:
            prev_close = float(df_recent["Close"].iloc[-2])
            change = today_close - prev_close
            change_ratio = (change / prev_close) * 100 if prev_close != 0 else 0
            
            high_date_str = high_date.strftime('%Y-%m-%d')
            
            high_new_macros.append({
                "구분": category,
                "지표명": name,
                "티커": ticker,
                "기존최고가달성일": high_date_str,
                "기존최고가": round(max_close_past, 2),
                "당일종가": round(today_close, 2),
                "대비": round(change, 2),
                "등락률": round(change_ratio, 2)
            })
            
    df_res = pd.DataFrame(high_new_macros)
    if not df_res.empty:
        df_res = df_res.sort_values(by=["구분", "지표명"])
    return df_res

if __name__ == "__main__":
    today = datetime.today()
    
    # 최근 20일간의 영업일 목록 가져오기 (마지막 2영업일을 구하기 위함)
    start_date_limit = (today - timedelta(days=20)).strftime("%Y%m%d")
    today_str = today.strftime("%Y%m%d")
    
    business_days = get_market_business_days(start_date_limit, today_str)
    
    TARGET_DATE = None  # 예: "2026-06-03"
    
    if TARGET_DATE is not None:
        target_dates = [pd.to_datetime(TARGET_DATE)]
    else:
        # 최근 2개 영업일 대상
        if len(business_days) >= 2:
            target_dates = [pd.to_datetime(d) for d in business_days[-2:]]
        else:
            target_dates = [pd.to_datetime(d) for d in business_days]
            
    output_dir = os.path.join(BASE_DIR, "result", "60day_high")
    os.makedirs(output_dir, exist_ok=True)
    
    for t_date in target_dates:
        t_date_str = t_date.strftime("%Y%m%d")
        result = run_macro_screener(t_date)
        
        file_path = os.path.join(output_dir, f"{t_date_str}_macro.csv")
        
        if not result.empty:
            print(f"\n★ 60일 신고가 경신 매크로 지표 - {t_date.strftime('%Y-%m-%d')} (총 {len(result)}개) ★")
            print(result.to_string(index=False))
            result.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"'{file_path}' 파일로 저장 완료되었습니다.")
        else:
            # 빈 결과 파일이라도 저장하여 데이터 일관성 보장
            result.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"\n{t_date.strftime('%Y-%m-%d')} 기준 60일 신고가를 경신한 매크로 지표가 없어 빈 파일로 저장했습니다.")
