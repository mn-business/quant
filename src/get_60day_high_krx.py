from datetime import datetime, timedelta
import os
import time
import pandas as pd
from pykrx import stock
from tqdm import tqdm
import FinanceDataReader as fdr

# KRX 로그인 환경 변수 설정 (.env 파일 또는 시스템 환경 변수에서 로드)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if "KRX_ID" not in os.environ or not os.environ["KRX_ID"]:
    raise ValueError("환경 변수 KRX_ID가 설정되지 않았습니다. 로컬 실행을 위해 .env 파일을 확인해 주세요.")
if "KRX_PW" not in os.environ or not os.environ["KRX_PW"]:
    raise ValueError("환경 변수 KRX_PW가 설정되지 않았습니다. 로컬 실행을 위해 .env 파일을 확인해 주세요.")

# 스크립트 위치 기준 상위 루트 디렉토리 구하기 (사이드 이펙트 방지)
# get_60day_high.py가 src/ 폴더 밑에 위치하게 되므로, 
# 이 파일의 2단계 상위 디렉토리가 프로젝트 루트가 됩니다.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 데이터 보관용 로컬 CSV 파일 경로를 절대 경로로 정의
DB_FILE = os.path.join(BASE_DIR, "db", "60day_high_krx.csv")

def get_market_business_days(start_date, end_date):
    """삼성전자(005930) 데이터를 기준으로 실제 주식시장 영업일 목록을 가져옵니다."""
    try:
        df = stock.get_market_ohlcv_by_date(start_date, end_date, "005930")
        return df.index.strftime("%Y%m%d").tolist()
    except Exception as e:
        print(f"[WARN] 영업일 목록 조회 실패: {e}")
        # 예외 발생 시 달력 날짜 기준으로 대체
        s = datetime.strptime(start_date, "%Y%m%d")
        e = datetime.strptime(end_date, "%Y%m%d")
        delta = e - s
        all_days = [(s + timedelta(days=i)).strftime("%Y%m%d") for i in range(delta.days + 1)]
        return all_days

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
                # 60일 신고가 계산을 위해 최소한 150일 이전의 과거 데이터도 포함되어 있어야 함
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

    # 3. 날짜별 전종목 데이터 가져오기 (종목 루프가 아닌 날짜 루프 -> 획기적 속도 향상 & 차단 회피)
    new_data_list = []
    
    for date_str in tqdm(target_days, desc="일자별 전종목 시세 동기화 중"):
        try:
            # 해당 날짜의 코스피 전체 종목 시세
            df_kospi = stock.get_market_ohlcv_by_ticker(date_str, market="KOSPI")
            # 해당 날짜의 코스닥 전체 종목 시세
            df_kosdaq = stock.get_market_ohlcv_by_ticker(date_str, market="KOSDAQ")
            
            # 각각 데이터가 있을 때 가공 및 병합
            for market_df in [df_kospi, df_kosdaq]:
                if not market_df.empty:
                    df_tmp = market_df.reset_index()
                    df_tmp.rename(columns={"티커": "종목코드"}, inplace=True)
                    df_tmp["날짜"] = pd.to_datetime(date_str)
                    # 기존 형식 컬럼만 선별 추출 (날짜, 종목코드, 시가, 고가, 저가, 종가, 거래량)
                    df_tmp = df_tmp[["날짜", "종목코드", "시가", "고가", "저가", "종가", "거래량"]]
                    new_data_list.append(df_tmp)
            
            # 하루치 가져온 후 서버 부하 및 차단 방지를 위한 최소한의 휴식
            time.sleep(0.5)
        except Exception as e:
            print(f"\n[ERROR] {date_str} 데이터 수집 중 오류: {e}")
            continue

    # 4. 기존 데이터와 신규 데이터 병합 후 파일 저장
    if new_data_list:
        df_new = pd.concat(new_data_list, ignore_index=True)
        df_new["날짜"] = pd.to_datetime(df_new["날짜"])

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
            
            # 당일 최고가 및 최저가
            today_high = df_recent["고가"].iloc[-1]
            today_low = df_recent["저가"].iloc[-1]
            
            # 파이썬 정밀 연산 및 int 캐스팅으로 int32 오버플로우 방지
            trade_amount = int(int(today_close) * int(today_volume))
            
            high_new_stocks.append(
                {
                    "종목코드": str(ticker).strip().zfill(6),
                    "당일최고가": int(today_high),
                    "당일최저가": int(today_low),
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
    # fdr을 통해 KRX 상장정보 가져오기
    try:
        df_krx = get_robust_krx_listing()
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

    # 결과 데이터프레임의 조인 키 정제
    df_res['종목코드'] = df_res['종목코드'].astype(str).str.strip().str.zfill(6)
    
    # 조인
    df_merged = pd.merge(df_res, df_krx, on='종목코드', how='left')
    df_merged = pd.merge(df_merged, df_kind_sub, on='종목코드', how='left')

    # 5. 우선주 등 미매핑 종목에 대해 본주(끝자리 0) 기준으로 섹터 재매핑
    missing_mask = df_merged['섹터A'].isna() | (df_merged['섹터A'] == '')
    if missing_mask.any() and not df_kind_sub.empty:
        df_merged.loc[missing_mask, '본주코드'] = df_merged.loc[missing_mask, '종목코드'].str[:-1] + '0'
        df_merged = pd.merge(df_merged, df_kind_sub, left_on='본주코드', right_on='종목코드', how='left', suffixes=('', '_본주'))
        df_merged = df_merged.reset_index(drop=True)
        
        # merge 이후 인덱스가 재설정되므로 missing_mask를 새로 계산
        missing_mask = df_merged['섹터A'].isna() | (df_merged['섹터A'] == '')
        df_merged.loc[missing_mask, '섹터A'] = df_merged.loc[missing_mask, '섹터A_본주']
        df_merged.loc[missing_mask, '섹터B'] = df_merged.loc[missing_mask, '섹터B_본주']
        df_merged.drop(columns=['본주코드', '종목코드_본주', '섹터A_본주', '섹터B_본주'], inplace=True, errors='ignore')

    df_merged['종목명'] = df_merged['종목명'].fillna('')
    # 종목명이 없는 데이터 필터링 제거
    df_merged = df_merged[df_merged['종목명'].str.strip() != '']
    
    df_merged['섹터A'] = df_merged['섹터A'].fillna('')
    df_merged['섹터B'] = df_merged['섹터B'].fillna('')
    df_merged['시장구분'] = df_merged['시장구분'].fillna('')

    # 6. 추가 수치 연산 (시가총액 = 당일종가 * 상장주식수)
    df_merged['상장주식수'] = pd.to_numeric(df_merged['상장주식수'], errors='coerce').fillna(0)
    
    # 시가총액: 억원 단위로 변환 (// 100,000,000)
    market_caps = (df_merged['당일종가'].astype(float) * df_merged['상장주식수'].astype(float)).astype('int64')
    df_merged['종료일 시가총액(억원)'] = (market_caps // 100_000_000).apply(lambda x: f"{x:,}")
    
    # 거래금액: 백만원 단위로 변환 (// 1,000,000)
    df_merged['종료일 거래금액(백만원)'] = (df_merged['종료일 거래금액'].astype('int64') // 1_000_000).apply(lambda x: f"{x:,}")
    
    # 기타 수치 칼럼들 3자리 콤마 문자열 형식으로 변환
    comma_cols = ['기존최고가', '당일최고가', '당일최저가', '당일종가', '대비', '종료일 거래량']
    for col in comma_cols:
        df_merged[col] = df_merged[col].astype('int64').apply(lambda x: f"{x:,}")

    # 7. 시장구분 소문자로 변환
    df_merged['시장구분'] = df_merged['시장구분'].str.lower()

    # 시장구분 내림차순, 섹터A 오름차순, 섹터B 오름차순 정렬
    df_merged = df_merged.sort_values(
        by=['시장구분', '섹터A', '섹터B'],
        ascending=[False, True, True]
    )

    # 8. 요청된 칼럼 순서로 정렬
    ordered_cols = [
        '섹터A', '섹터B', '종목코드', '종목명', '시장구분', 
        '기존최고가달성일', '기존최고가', '당일최고가', '당일최저가', '당일종가', '대비', '등락률', 
        '종료일 거래량', '종료일 거래금액(백만원)', '종료일 시가총액(억원)'
    ]
    
    existing_cols = [col for col in ordered_cols if col in df_merged.columns]
    return df_merged[existing_cols]
if __name__ == "__main__":
    # 1단계: 데이터 업데이트 (일자별 일괄 요청으로 초고속 및 차단 회피)
    total_data = update_and_get_data()

    # 특정 기준일(예: 2026-06-03)을 지정하여 그 날짜 기준으로 분석하려면 아래 변수에 날짜를 기입하세요.
    # None으로 설정하면 오늘 실시간 데이터를 포함한 최신 영업일 기준 데이터로 분석합니다.
    TARGET_DATE = None  # 예: "2026-06-03"

    if TARGET_DATE is not None:
        total_data = total_data[total_data["날짜"] <= pd.to_datetime(TARGET_DATE)]
        print(f"\n[INFO] {TARGET_DATE} 이전 데이터만 필터링하여 분석을 진행합니다.")

    # 2단계: 로컬 데이터를 기반으로 실시간 신고가 연산 (서버 호출 없음 -> 1~2초 만에 종료)
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
        
        file_path = os.path.join(output_dir, f"{t_date_str}_krx.csv")
        
        if not result.empty:
            print(f"\n★ 60일 신고가 경신 종목 - {t_date.strftime('%Y-%m-%d')} (총 {len(result)}개) ★")
            print(result.to_string(index=False))
            result.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"'{file_path}' 파일로 저장 완료되었습니다.")
        else:
            # 기존에 결과물이 있었으나 수정되어 비게 된 경우를 대비해 빈 CSV로 덮어씁니다.
            result.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"\n{t_date.strftime('%Y-%m-%d')} 기준 60일 신고가를 경신한 종목이 없어 빈 파일로 저장했습니다.")
