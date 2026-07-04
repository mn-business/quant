# 260704-대만 가권(TWSE) 종목 추가 계획

본 계획서는 `src/get_60day_high_yf.py` 스크립트에 대만 가권 지수(TWSE) 상장 종목군을 분석 대상으로 추가하기 위한 세부 변경 계획을 담고 있습니다.

## 1. 개요
* **목적**: 대만 증권거래소(TWSE)에 상장된 종목들을 수집 및 분석 대상에 포함하여 글로벌 60일 신고가 모니터링 범위를 확장합니다.
* **위치**: `src/get_60day_high_yf.py`의 수집 대상 로드, 메타 정보 구축, 결과 시장 매핑 블록
* **대상 파일**: `src/get_60day_high_yf.py`

---

## 2. 변경 계획 상세

### A. 대만 TWSE 종목 리스트 로드 및 매핑 추가
1. **대만 OpenAPI를 통한 종목 로드** (`update_and_get_data` 함수 내)
   * 대만 증권거래소 OpenAPI (`https://openapi.twse.com.tw/v1/opendata/t187ap03_L`)를 사용하여 대만 상장 종목 목록을 다운로드합니다.
   * 야후 파이낸스 티커 접미사(`.TW`)를 부여하여 `ticker_map`에 적재합니다.
     ```python
     # (3) 대만 TWSE 종목 목록 로드
     try:
         import requests
         url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
         res = requests.get(url, timeout=10)
         if res.status_code == 200:
             data = res.json()
             for item in data:
                 code = str(item.get('公司代號', '')).strip()
                 if code.isdigit():  # 일반 주식 코드 필터링
                     yf_ticker = f"{code}.TW"
                     ticker_map[code] = yf_ticker
                     ticker_map_reverse[yf_ticker] = code
     except Exception as e:
         print(f"[WARN] 대만 TWSE 종목 목록 로드 실패: {e}")
     ```

### B. 대만 TWSE 메타 정보 구축 추가
1. **대만 주식 메타 정보 구축** (`screen_60day_high` 함수 내)
   * 대만 OpenAPI의 `'公司簡稱'`(또는 `'公司名稱'`) 및 `'產業別'`(산업 분류) 정보를 결합하여 메타 데이터프레임을 생성합니다.
     ```python
     # 3. 대만 TWSE 정보 구축
     df_tw_meta = pd.DataFrame(columns=['종목코드', '종목명', '시장구분', '상장주식수', '섹터A', '섹터B'])
     try:
         import requests
         url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
         res = requests.get(url, timeout=10)
         if res.status_code == 200:
             data = res.json()
             tw_rows = []
             for item in data:
                 code = str(item.get('公司代號', '')).strip()
                 name = str(item.get('公司簡稱', '')).strip() or str(item.get('公司名稱', '')).strip()
                 industry = str(item.get('產業別', '')).strip()
                 if code.isdigit():
                     tw_rows.append({
                         '종목코드': code,
                         '종목명': name,
                         '시장구분': 'TWSE',
                         '상장주식수': 0,
                         '섹터A': industry,
                         '섹터B': ''
                     })
             df_tw_meta = pd.DataFrame(tw_rows)
     except Exception as e:
         print(f"[WARN] 대만 TWSE 메타 정보 로드 실패: {e}")
     ```
2. **메타 정보 결합 목록에 대만(TWSE) 추가**
   * `df_unified_meta` 결합 시 `df_tw_meta`를 추가합니다.
     ```python
     df_unified_meta = pd.concat([df_krx_merged, df_us_meta, df_tw_meta, df_jp_meta], ignore_index=True)
     ```

### C. 결과 파일 저장 및 분기 처리 변경
1. **시장별 분기 저장 정의 수정** (라인 570-580 영역)
   * `markets_mapping` 딕셔너리에 `"twse"` 항목을 추가합니다.
   * 대만 가권 지수 종목 분석 결과는 `{t_date_str}_yf_twse.csv` 파일명으로 자동 저장됩니다.
     ```python
         # 시장별 분리 처리 매핑 정의
         markets_mapping = {
             "krx": result[result['시장구분'].isin(['kospi', 'kosdaq'])],
             "nasdaq": result[result['시장구분'] == 'nasdaq'],
             "twse": result[result['시장구분'] == 'twse'],
             # "tse": result[result['시장구분'] == 'tse']
         }
     ```

---

## 3. 검증 계획
* 소스 코드 변경 작업 및 실제 테스트 수행은 사용자의 지시("코드 수정하지마. 테스트 수행하지마.")에 따라 배제하며, 추후 승인 시 진행합니다.
