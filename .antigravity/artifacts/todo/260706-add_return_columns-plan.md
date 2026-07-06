# 260706-종가 상승률 컬럼 추가 계획

본 계획서는 `src/get_60day_high_krx.py` 및 `src/get_60day_high_yf.py` 결과 파일에 "3개월 종가 상승률" 및 "1주 종가 상승률" 정보를 추가하기 위한 세부 변경 계획을 담고 있습니다.

## 1. 개요
* **목적**: 60일 신고가 분석 결과물에 최근 3개월(60영업일) 및 1주(5영업일) 동안의 종가 상승률 정보를 추가하여 종목의 단기/중기 추세를 파악할 수 있도록 합니다.
* **위치**: 결과 CSV 및 출력 테이블의 `당일종가` 컬럼 바로 뒤 (즉, `대비` 컬럼 앞)
* **대상 파일**:
  1. `src/get_60day_high_krx.py`
  2. `src/get_60day_high_yf.py`

---

## 2. 변경 계획 상세

### A. `src/get_60day_high_krx.py` 수정 계획
1. **1주 및 3개월 전 종가 데이터 추출 및 상승률 계산** (`screen_60day_high` 함수 내)
   * `group` DataFrame으로부터 1주 전(5영업일 전, `-6`번째 행) 및 3개월 전(60영업일 전, `-61`번째 행)의 종가를 가져와 상승률을 계산합니다.
   * `df_total` 데이터 Pruning에 의해 최소 100영업일까지 보존되므로 60영업일 전 데이터는 유효하게 존재합니다. (단, 신규 상장 등으로 데이터가 부족한 경우 예외 처리)
   * 계산 로직 예시:
     ```python
     # 1주 전(5영업일 전) 종가 추출 및 상승률 계산
     close_1w = group["종가"].iloc[-6]
     rate_1w = round(((today_close - close_1w) / close_1w) * 100, 2) if close_1w != 0 else 0.0

     # 3개월 전(60영업일 전) 종가 추출 및 상승률 계산 (안전 장치 추가)
     if len(group) >= 61:
         close_3m = group["종가"].iloc[-61]
     else:
         close_3m = group["종가"].iloc[0]
     rate_3m = round(((today_close - close_3m) / close_3m) * 100, 2) if close_3m != 0 else 0.0
     ```

2. **수집 데이터 딕셔너리에 추가**
   * `high_new_stocks.append` 시 `3개월 종가 상승률` 및 `1주 종가 상승률` 컬럼 매핑:
     * 가독성을 위해 기호(`+` 또는 `-`) 및 `%` 단위를 포함한 문자열로 포맷팅하거나, 정렬 등의 편의를 위해 소수점 둘째 자리 float로 직접 저장하는 방안이 있습니다. 본 계획에서는 가독성을 높이기 위해 문자열 포맷팅(예: `+12.34%`) 방식을 제안합니다.
     ```python
     high_new_stocks.append(
         {
             "종목코드": str(ticker).strip().zfill(6),
             "당일최고가": int(today_high),
             "당일최저가": int(today_low),
             "당일종가": int(today_close),
             "3개월 종가 상승률": f"{rate_3m:+.2f}%",
             "1주 종가 상승률": f"{rate_1w:+.2f}%",
             "대비": int(change),
             "등락률": round(change_ratio, 2),
             ...
         }
     )
     ```

3. **컬럼 정렬 순서 정의 (`ordered_cols`) 변경**
   * `'3개월 종가 상승률'`과 `'1주 종가 상승률'`을 `'당일종가'` 뒤에 배치:
     ```python
     ordered_cols = [
         '섹터A', '섹터B', '종목코드', '종목명', '시장구분', 
         '기존최고가달성일', '기존최고가', '당일최고가', '당일최저가', '당일종가', 
         '3개월 종가 상승률', '1주 종가 상승률', '대비', '등락률', 
         '종료일 거래량', '종료일 거래금액(백만원)', '종료일 시가총액(억원)'
     ]
     ```

### B. `src/get_60day_high_yf.py` 수정 계획
1. **1주 및 3개월 전 종가 데이터 추출 및 상승률 계산** (`screen_60day_high` 함수 내)
   * KRX와 동일하게 `group` DataFrame을 기준으로 1주 전(`-6`) 및 3개월 전(`-61` 혹은 가장 오래된 행) 데이터를 참조하여 상승률을 계산합니다.
   * 계산 로직 예시:
     ```python
     close_1w = group["종가"].iloc[-6]
     rate_1w = round(((today_close - close_1w) / close_1w) * 100, 2) if close_1w != 0 else 0.0

     if len(group) >= 61:
         close_3m = group["종가"].iloc[-61]
     else:
         close_3m = group["종가"].iloc[0]
     rate_3m = round(((today_close - close_3m) / close_3m) * 100, 2) if close_3m != 0 else 0.0
     ```

2. **수집 데이터 딕셔너리에 추가**
   * `high_new_stocks.append` 시 동일하게 기호와 단위를 포맷팅하여 추가:
     ```python
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
             ...
         }
     )
     ```

3. **컬럼 정렬 순서 정의 (`ordered_cols`) 변경**
   * `'3개월 종가 상승률'`과 `'1주 종가 상승률'`을 `'당일종가'` 뒤에 배치:
     ```python
     ordered_cols = [
         '섹터A', '섹터B', '종목코드', '종목명', '시장구분', 
         '기존최고가달성일', '기존최고가', '당일최고가', '당일최저가', '당일종가', 
         '3개월 종가 상승률', '1주 종가 상승률', '대비', '등락률', 
         '종료일 거래량', '종료일 거래금액(백만원)', '종료일 시가총액(억원)'
     ]
     ```

---

## 3. 검증 계획
* 소스 코드 변경 작업 및 실제 테스트 수행은 사용자의 지시("코드 수정하지마. 테스트 수행하지마.")에 따라 배제하며, 추후 승인 시 진행합니다.
