# 260704-당일 최고가 및 최저가 컬럼 추가 계획

본 계획서는 `src/get_60day_high_krx.py` 및 `src/get_60day_high_yf.py` 결과 파일에 당일 최고가 및 당일 최저가 정보를 추가하기 위한 세부 변경 계획을 담고 있습니다.

## 1. 개요
* **목적**: 60일 신고가 분석 결과물에 당일 최고가('고가') 및 당일 최저가('저가') 정보를 추가하여 가시성을 확보합니다.
* **위치**: 결과 CSV 및 출력 테이블의 `당일종가` 컬럼 바로 앞 (즉, `기존최고가` 컬럼 뒤)
* **대상 파일**:
  1. `src/get_60day_high_krx.py`
  2. `src/get_60day_high_yf.py`

---

## 2. 변경 계획 상세

### A. `src/get_60day_high_krx.py` 수정 계획
1. **당일 고가 및 저가 데이터 추출** (`screen_60day_high` 함수 내)
   * `df_recent` DataFrame으로부터 당일 최고가(고가) 및 당일 최저가(저가) 추출:
     ```python
     today_high = df_recent["고가"].iloc[-1]
     today_low = df_recent["저가"].iloc[-1]
     ```
2. **수집 데이터 딕셔너리에 추가**
   * `high_new_stocks.append` 시 `당일최고가` 및 `당일최저가` 데이터 매핑:
     ```python
     high_new_stocks.append(
         {
             "종목코드": str(ticker).strip().zfill(6),
             "당일최고가": int(today_high),
             "당일최저가": int(today_low),
             "당일종가": int(today_close),
             ...
         }
     )
     ```
3. **천 단위 콤마 포맷팅 대상 컬럼에 추가**
   * `comma_cols` 리스트에 `'당일최고가'` 및 `'당일최저가'` 추가:
     ```python
     comma_cols = ['기존최고가', '당일최고가', '당일최저가', '당일종가', '대비', '종료일 거래량']
     ```
4. **컬럼 정렬 순서 정의 (`ordered_cols`) 변경**
   * `'당일최고가'`와 `'당일최저가'`를 `'당일종가'` 앞에 배치:
     ```python
     ordered_cols = [
         '섹터A', '섹터B', '종목코드', '종목명', '시장구분', 
         '기존최고가달성일', '기존최고가', '당일최고가', '당일최저가', '당일종가', '대비', '등락률', 
         '종료일 거래량', '종료일 거래금액(백만원)', '종료일 시가총액(억원)'
     ]
     ```

### B. `src/get_60day_high_yf.py` 수정 계획
1. **당일 고가 및 저가 데이터 추출** (`screen_60day_high` 함수 내)
   * `df_recent` DataFrame으로부터 당일 최고가(고가) 및 당일 최저가(저가) 추출:
     ```python
     today_high = df_recent["고가"].iloc[-1]
     today_low = df_recent["저가"].iloc[-1]
     ```
2. **수집 데이터 딕셔너리에 추가**
   * `high_new_stocks.append` 시 `당일최고가` 및 `당일최저가` 데이터 매핑:
     ```python
     high_new_stocks.append(
         {
             "종목코드": ticker_str,
             "당일최고가": float(today_high),
             "당일최저가": float(today_low),
             "당일종가": float(today_close),
             ...
         }
     )
     ```
3. **시장 구분별 포맷팅 루프 추가**
   * 포맷팅할 컬럼 목록에 `'당일최고가'` 및 `'당일최저가'` 추가:
     ```python
     for col in ['당일최고가', '당일최저가', '당일종가', '대비', '기존최고가']:
         df_merged[col] = df_merged.apply(lambda r: format_row_value(r, col), axis=1)
     ```
4. **컬럼 정렬 순서 정의 (`ordered_cols`) 변경**
   * `'당일최고가'`와 `'당일최저가'`를 `'당일종가'` 앞에 배치:
     ```python
     ordered_cols = [
         '섹터A', '섹터B', '종목코드', '종목명', '시장구분', 
         '기존최고가달성일', '기존최고가', '당일최고가', '당일최저가', '당일종가', '대비', '등락률', 
         '종료일 거래량', '종료일 거래금액(백만원)', '종료일 시가총액(억원)'
     ]
     ```

---

## 3. 검증 계획
* 소스 코드 변경 작업 및 실제 테스트 수행은 사용자의 지시("코드 수정하지마. 테스트 수행하지마.")에 따라 배제하며, 추후 승인 시 진행합니다.
