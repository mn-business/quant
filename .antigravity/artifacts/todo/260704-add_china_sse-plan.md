# 260704-중국 상하이 종합(SSE) 종목 추가 계획

본 계획서는 `src/get_60day_high_yf.py` 스크립트에 중국 상하이 증권거래소(SSE) 상장 종목군을 분석 대상으로 추가하기 위한 세부 변경 계획을 담고 있습니다.

## 1. 개요
* **목적**: 중국 상하이 증권거래소(SSE)에 상장된 종목들을 수집 및 분석 대상에 포함하여 글로벌 60일 신고가 모니터링 범위를 확장합니다.
* **위치**: `src/get_60day_high_yf.py`의 수집 대상 로드, 메타 정보 구축, 결과 시장 매핑 블록
* **대상 파일**: `src/get_60day_high_yf.py`

---

## 2. 변경 계획 상세

### A. 중국 SSE 종목 리스트 로드 및 매핑 추가
1. **상하이 종목 다운로드 및 매핑** (`update_and_get_data` 함수 내)
   * FinanceDataReader의 `fdr.StockListing('SSE')`을 활용하여 상하이 증권거래소 상장 종목 목록을 다운로드합니다.
   * 야후 파이낸스 티커 접미사(`.SS`)를 부여하여 `ticker_map`에 적재합니다.
     ```python
     # (4) 중국 SSE 종목 목록 로드
     try:
         df_sse = fdr.StockListing('SSE')
         for _, row in df_sse.iterrows():
             symbol = str(row['Symbol']).strip()
             yf_ticker = f"{symbol}.SS"
             ticker_map[symbol] = yf_ticker
             ticker_map_reverse[yf_ticker] = symbol
     except Exception as e:
         print(f"[WARN] SSE 종목 목록 로드 실패: {e}")
     ```

### B. 중국 SSE 메타 정보 구축 추가
1. **상하이 주식 메타 정보 구축** (`screen_60day_high` 함수 내)
   * `fdr.StockListing('SSE')` 데이터를 가공해 종목 정보인 `df_sse_meta`를 구성합니다.
     ```python
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
     ```
2. **메타 정보 결합 목록에 중국(SSE) 추가**
   * `df_unified_meta` 결합 시 `df_sse_meta`를 추가합니다.
     ```python
     df_unified_meta = pd.concat([df_krx_merged, df_us_meta, df_tw_meta, df_sse_meta, df_jp_meta], ignore_index=True)
     ```

### C. 결과 파일 저장 및 분기 처리 변경
1. **시장별 분기 저장 정의 수정** (라인 575-590 영역)
   * `markets_mapping` 딕셔너리에 `"sse"` 항목을 추가합니다.
   * 상하이 종합 지수 종목 분석 결과는 `{t_date_str}_yf_sse.csv` 파일명으로 자동 저장됩니다.
     ```python
         # 시장별 분리 처리 매핑 정의
         markets_mapping = {
             "krx": result[result['시장구분'].isin(['kospi', 'kosdaq'])],
             "nasdaq": result[result['시장구분'] == 'nasdaq'],
             "twse": result[result['시장구분'] == 'twse'],
             "sse": result[result['시장구분'] == 'sse'],
             # "tse": result[result['시장구분'] == 'tse']
         }
     ```

---

## 3. 검증 계획
* 소스 코드 변경 작업 및 실제 테스트 수행은 사용자의 지시("코드 수정하지마. 테스트 수행하지마.")에 따라 배제하며, 추후 승인 시 진행합니다.
