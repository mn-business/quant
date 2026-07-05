# 260704-대만 가권(TWSE) 결과 누락 원인 분석 및 대안

본 분석서는 `result/60day_high/20260703_yf_twse.csv` 파일에 헤더만 존재하고 실제 결과 데이터가 누락된 현상의 원인을 진단하고 이에 대한 해결 방안을 제안합니다.

---

## 1. 현상 및 진단

### A. 현상
* `20260702_yf_twse.csv` 및 `20260703_yf_twse.csv` 파일의 크기가 244바이트로 고정되어 있으며, 열어보면 컬럼 헤더만 있고 데이터 행이 전혀 존재하지 않음.
* `db/60day_high_yf.csv` 파일 내에 대만 종목코드(예: `2330` 등) 및 `.TW` 접미사가 부착된 거래 데이터가 전혀 누적되어 있지 않음.

### B. 예상 원인 분석

#### 1) 대만 OpenAPI 서버의 요청 차단 (가장 높은 확률)
* **원인**: 현재 `src/get_60day_high_yf.py` 코드 내 대만 종목 수집 부분은 다음과 같이 작성되어 있습니다:
  ```python
  res = requests.get(url, timeout=10)
  ```
  이때 별도의 `User-Agent` 헤더를 설정하지 않아 기본 `python-requests/2.x.x` 헤더로 요청이 전송됩니다.
* **영향**: 대만 증권거래소(TWSE) OpenAPI 서버(`openapi.twse.com.tw`) 또는 방화벽에서 봇 트래픽으로 판단하여 `403 Forbidden`을 반환했거나, GitHub Actions 러너의 클라우드 IP 대역을 차단하여 예외가 발생했을 가능성이 높습니다.
* **결과**: 예외 처리(`try-except Exception`)에 의해 에러 로그만 출력되고 `ticker_map`에 대만 종목이 하나도 등록되지 않아 수집 프로세스 자체가 스킵되었습니다.

#### 2) 대만 시장의 60일 신고가 종목 실제 부재
* **원인**: 2026-07-02 ~ 2026-07-03 기간 동안 대만 주식 시장(TWSE)에서 종가 기준 60일 최고가를 경신한 종목이 실제로 존재하지 않았을 가능성입니다.
* **평가**: 다만 DB 파일(`db/60day_high_yf.csv`)에도 대만 주식 데이터가 전혀 누적되어 있지 않다는 점으로 미루어 볼 때, 실제 부재보다는 **데이터 수집 단계 실패**로 판정됩니다.

---

## 2. 해결 방안 (코드 개선 계획)

대만 종목 데이터를 보다 견고하게 가져오기 위해 두 가지 방어 코드를 구현할 수 있습니다.

### 개선안 1: 브라우저 User-Agent 헤더 추가
기본 `requests` 호출에 브라우저처럼 보이도록 User-Agent 헤더를 주입합니다.
```python
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
res = requests.get(url, headers=headers, timeout=10)
```

### 개선안 2: ISIN 공식 웹 페이지 크롤링을 통한 Fallback 처리
OpenAPI (`openapi.twse.com.tw`) 호출이 차단되거나 장애가 날 경우를 대비하여, 대만 증권거래소의 공식 ISIN 안내 페이지(`https://isin.twse.com.tw/isin/C_public.jsp?strMode=2`)에서 HTML 표를 파싱해 종목 목록을 복구하는 이중화(Fallback) 구조를 설계합니다.

#### Fallback 구현 예시:
```python
def get_taiwan_tickers():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    # 1. 1차 시도: OpenAPI JSON
    try:
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return [(item.get('公司代號', '').strip(), 
                     item.get('公司簡稱', '').strip() or item.get('公司名稱', '').strip(), 
                     item.get('產業別', '').strip()) for item in res.json()]
    except Exception as e:
        print(f"[WARN] TWSE OpenAPI 1차 조회 실패: {e}")

    # 2. 2차 시도 (Fallback): ISIN Public HTML Scraping
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            res.encoding = 'big5'  # 대만 전통 한자 인코딩 설정
            dfs = pd.read_html(res.text)
            df = dfs[0]
            # 데이터 정제 및 주식 종목만 필터링
            tickers = []
            for idx, row in df.iterrows():
                val = str(row[0]).strip()
                # '코드 + 공백 + 종목명' 구조 분리 (예: "2330 台積電")
                parts = val.split('\u3000')
                if len(parts) >= 2 and parts[0].isdigit():
                    code = parts[0]
                    name = parts[1]
                    # 업종 정보는 5번째 열에 위치
                    industry = str(row[4]).strip() if len(row) > 4 else ''
                    tickers.append((code, name, industry))
            return tickers
    except Exception as e:
        print(f"[ERROR] TWSE ISIN 2차 백업 조회 실패: {e}")
        
    return []
```

---

## 3. 검증 계획
* 소스 코드 변경 작업 및 실제 테스트 수행은 사용자의 지시("코드 수정하지마. 테스트 수행하지마.")에 따라 배제하며, 추후 승인 시 진행합니다.
