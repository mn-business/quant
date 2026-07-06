# 260706-신고가 결과 파일의 월별(YYYYMM) 폴더 관리 계획

본 계획서는 `result/60day_high/` 디렉토리 하위에 매 영업일마다 수십 개의 시장별 결과 CSV 파일이 누적되어 발생하는 파일 관리 상의 복잡도 및 오버헤드를 해결하고, 연/월 단위(`YYYYMM`)로 디렉토리를 자동 분류하여 저장 및 관리하기 위한 설계 및 이행 계획을 제시합니다.

---

## 1. 개요 및 문제 진단

### A. 현재 상황
* 현재 스크리너 실행 결과 파일은 `result/60day_high/` 디렉토리 하위에 바로 생성됩니다.
  - 예시: `result/60day_high/20260703_yf_nasdaq.csv`, `20260703_krx.csv`, `20260703_macro.csv` 등
* 데이터 수집이 매일 이루어지기 때문에 해당 폴더 내의 파일 개수가 수백~수천 개로 증가하여 파일 탐색 속도가 느려지고 파일 관리 오버헤드가 누적되고 있습니다.

### B. 개선 방향
* 분석 기준일(`t_date`)의 연/월 정보를 추출하여 `YYYYMM` 형식의 서브디렉토리를 자동으로 생성합니다.
  - 예시: `result/60day_high/202607/20260703_yf_nasdaq.csv`
* 이를 통해 디렉토리 탐색 성능을 대폭 향상시키고 월별 결과를 편리하게 관리 및 추적할 수 있도록 개선합니다.

---

## 2. 상세 구현 계획

### A. 대상 파일
1. `src/get_60day_high_yf.py`
2. `src/get_60day_high_krx.py`

### B. 변경할 주요 로직 설계

각 스크립트의 결과물 저장(`to_csv`) 및 디렉토리 생성(`makedirs`) 로직을 분석 기준일(`t_date`) 기준으로 다음과 같이 수정합니다.

#### 1) [get_60day_high_yf.py](file:///d:/dev/work/quant/src/get_60day_high_yf.py) 수정 계획 (반영 완료)
* **변경 내용**:
  ```python
  for t_date in target_dates:
      t_date_str = t_date.strftime("%Y%m%d")
      month_str = t_date.strftime("%Y%m") # "YYYYMM" 추출
      
      # 월별 서브디렉토리 생성
      monthly_output_dir = os.path.join(output_dir, month_str)
      os.makedirs(monthly_output_dir, exist_ok=True)
      
      ...
      for m_name, df_m in markets_mapping.items():
          file_path = os.path.join(monthly_output_dir, f"{t_date_str}_yf_{m_name}.csv")
  ```

#### 2) [get_60day_high_krx.py](file:///d:/dev/work/quant/src/get_60day_high_krx.py) 수정 계획 (반영 완료)
* **변경 내용**:
  ```python
  for t_date in target_dates:
      t_date_str = t_date.strftime("%Y%m%d")
      month_str = t_date.strftime("%Y%m") # "YYYYMM" 추출
      
      # 월별 서브디렉토리 생성
      monthly_output_dir = os.path.join(output_dir, month_str)
      os.makedirs(monthly_output_dir, exist_ok=True)
      
      ...
      file_path = os.path.join(monthly_output_dir, f"{t_date_str}_krx.csv")
  ```

---

## 3. 검증 계획
* 소스 코드 변경 작업이 승인되어 소스 반영을 완료했습니다.
* 실제 수집 테스트 및 파이썬 실행 검증은 사용자 로컬 환경에서 직접 실행하여 결과 파일이 YYYYMM 서브폴더에 저장되는지 최종 확인합니다.
