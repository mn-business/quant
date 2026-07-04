# 260704-S&P500 지수를 나스닥 종합 지수로 변경 계획

본 계획서는 `src/get_60day_high_yf.py` 스크립트에서 수집 및 분석 대상 미국 지수를 기존 **S&P500**에서 **나스닥(NASDAQ)** 종목군으로 변경하기 위한 세부 변경 계획을 담고 있습니다.

## 1. 개요
* **목적**: 미국 시장 분석 대상을 S&P500 지수 구성 종목에서 나스닥(NASDAQ)에 상장된 전체 종목으로 변경합니다.
* **위치**: `src/get_60day_high_yf.py`의 미국 주식 수집, 정보 결합, 포맷팅 및 파일 저장 처리 블록
* **대상 파일**: `src/get_60day_high_yf.py`

---

## 2. 변경 계획 상세

### A. NASDAQ 종목 리스트 로드 및 매핑 수정
1. **NASDAQ 종목 다운로드 및 매핑** (라인 200-210 영역)
   * 기존 `fdr.StockListing('S&P500')` 호출을 `fdr.StockListing('NASDAQ')`로 변경합니다.
   * `df_nasdaq` DataFrame에서 각 종목의 심볼을 파싱하여 `ticker_map`에 적재합니다.
     ```python
     # (2) 미국 NASDAQ 종목 목록 로드
     try:
         df_nasdaq = fdr.StockListing('NASDAQ')
         for _, row in df_nasdaq.iterrows():
             symbol = str(row['Symbol']).strip()
             yf_ticker = symbol.replace('.', '-')
             ticker_map[symbol] = yf_ticker
             ticker_map_reverse[yf_ticker] = symbol
     except Exception as e:
         print(f"[WARN] NASDAQ 종목 목록 로드 실패: {e}")
     ```

### B. NASDAQ 메타 정보 구축 수정
1. **미국 NASDAQ 메타 정보 결합** (라인 452-466 영역)
   * FinanceDataReader의 `NASDAQ` 리스팅에서 제공하는 `'Industry'` 및 `'IndustryCode'` 컬럼 구조를 기준으로 미국 주식 메타 정보인 `df_us_meta`를 재정의합니다.
     ```python
     # 2. 미국 NASDAQ 정보 구축
     df_us_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
     try:
         df_nasdaq = fdr.StockListing('NASDAQ')
         df_us_meta = pd.DataFrame({
             '종목코드': df_nasdaq['Symbol'].astype(str).str.strip(),
             '종목명': df_nasdaq['Name'],
             '시장구분': 'NASDAQ',
             '상장주식수': 0,
             '섹터A': df_nasdaq['Industry'].fillna(''),
             '섹터B': df_nasdaq['IndustryCode'].fillna('') if 'IndustryCode' in df_nasdaq.columns else ''
         })
     except Exception as e:
         print(f"[WARN] fdr NASDAQ 메타 정보 로드 실패: {e}")
     ```

### C. 포맷팅 및 시장구분 조건 수정
1. **종료일 거래금액 포맷팅 수정** (라인 506-510 영역)
   * 시장구분이 `'NASDAQ'`인 경우 달러 단위 표기를 위해 소수점 둘째 자리 포맷팅을 적용합니다.
     ```python
     df_merged['종료일 거래금액(백만원)'] = df_merged.apply(
         lambda r: f"{int(r['종료일 거래금액'] // 1_000_000):,}" if str(r['시장구분']).upper() in ['KOSPI', 'KOSDAQ']
         else f"{r['종료일 거래금액'] / 1_000_000:,.2f}" if str(r['시장구분']).upper() == 'NASDAQ'
         else f"{int(r['종료일 거래금액'] // 1_000_000):,}", axis=1
     )
     ```
2. **가격 및 대비 수치 포맷팅 수정** (라인 513-524 영역)
   * `format_row_value` 내에서 `'NASDAQ'` 시장 구분일 때 달러 포맷팅을 유지하도록 처리합니다.
     ```python
         elif market == 'NASDAQ':
             return f"{val:,.2f}"
     ```

### D. 결과 파일 저장 및 분기 처리 변경
1. **시장별 분기 저장 정의 수정** (라인 575-580 영역)
   * `markets_mapping` 딕셔너리에서 `"sp500"` 항목을 `"nasdaq"`으로 변경합니다.
   * `nasdaq` 결과는 `{t_date_str}_yf_nasdaq.csv` 파일명으로 저장됩니다.
     ```python
         # 시장별 분리 처리 매핑 정의
         markets_mapping = {
             "krx": result[result['시장구분'].isin(['kospi', 'kosdaq'])],
             "nasdaq": result[result['시장구분'] == 'nasdaq'],
             # "tse": result[result['시장구분'] == 'tse']
         }
     ```

---

## 3. 검증 계획
* 소스 코드 변경 작업 및 실제 테스트 수행은 사용자의 지시("코드 수정하지마. 테스트 수행하지마.")에 따라 배제하며, 추후 승인 시 진행합니다.
