# GitHub Actions 자동 스크리닝 파이프라인 가이드

`src/get_60day_high.py` 프로그램을 장 종료 시각에 자동으로 가동하고, 생성된 결과물(`result/60day_high/`)을 GitHub 저장소에서 안전하게 직접 다운로드받을 수 있도록 구성하는 가이드입니다.

---

## 1. 자동화 가동 메커니즘 (GitHub Actions Workflow)

1. **스케줄러 트리거**: 매일 평일(월~금) 한국 시각으로 **오후 4시 30분(16:30 KST)**에 가상 실행 컴퓨터(GitHub Actions Runner)가 자동으로 가동됩니다.
2. **패키지 복구**: 리포지토리 코드를 불러오고, 파이썬 패키지들(`pandas`, `pykrx` 등)을 신속하게 복구 및 캐싱 설치합니다.
3. **분석 수행**: `python src/get_60day_high.py`를 실행하여 60일 신고가 종목을 분석합니다.
4. **저장 및 푸시**: 실행 과정에서 업데이트된 캐시 데이터베이스(`db/60day_high.csv`)와 새로 생성된 당일자 신고가 결과 파일(`result/60day_high/60일_신고가_결과_YYYYMMDD.csv`)을 **저장소에 자동으로 `git commit` 및 `push`**합니다.
5. **결과물 다운로드**: 분석이 끝나면 GitHub 리포지토리의 `result/60day_high` 폴더에 즉시 파일이 업데이트되므로, 저장소에서 간편하게 다운로드받거나 확인하실 수 있습니다.

---

## 2. 프로젝트 반영 사항

### 1) [NEW] 워크플로우 정의 파일 [get_60day_high.yml](file:///d:/dev/work/quant/.github/workflows/get_60day_high.yml)
* **스케줄 설정**: `cron: '30 7 * * 1-5'` (UTC 07:30 = KST 16:30)
* **보안 환경변수 처리**: `KRX_ID`와 `KRX_PW`를 저장소 암호화 비밀변수(Secrets)와 연동할 수 있도록 매핑했습니다.
* **수동 트리거 지원**: `workflow_dispatch` 설정이 추가되어 있어, GitHub 웹 화면에서 **[Run workflow]** 버튼을 눌러 평일 시간 외에도 언제든지 즉석에서 수동 실행하실 수 있습니다.

### 2) [MODIFY] 자격증명 폴백 처리 [get_60day_high.py](file:///d:/dev/work/quant/src/get_60day_high.py)
* 기존에는 `os.environ` 값을 하드코딩으로 무조건 덮어씌웠기 때문에 GitHub Actions의 Secrets 값이 오버라이트되는 부작용이 있었습니다.
* 이를 방어하여 외부 환경변수(`Secrets`)가 주입되지 않았을 때만 임시 하드코딩 계정이 동작하도록 개선하여 로컬 호환성과 자동화 호환성을 동시에 잡았습니다.
```python
# KRX 로그인 환경 변수 설정 (기존 설정값이 없을 때만 기본 계정 주입)
if "KRX_ID" not in os.environ or not os.environ["KRX_ID"]:
    os.environ["KRX_ID"] = "moregorenine"
if "KRX_PW" not in os.environ or not os.environ["KRX_PW"]:
    os.environ["KRX_PW"] = "!2qweasdzxc"
```

---

## 3. GitHub에서 정상 동작하게 하기 위한 마지막 세팅 가이드

로컬 소스코드를 Git 저장소에 커밋 및 푸시하여 GitHub에 올리신 후, 브라우저로 GitHub 리포지토리에 접속하여 **딱 두 가지만 설정**해주시면 바로 자동 실행이 가동됩니다.

### ① GitHub Actions의 쓰기 권한 허용 (필수)
자동으로 계산된 결과 파일을 다시 GitHub 리포지토리에 푸시할 수 있게 쓰기 권한을 열어주어야 합니다.
1. GitHub 리포지토리 상단의 **`Settings`** 탭 클릭
2. 좌측 메뉴의 **`Actions`** -> **`General`** 클릭
3. 맨 아래 **`Workflow permissions`** 항목 찾기
4. **`Read and write permissions`**로 변경 후 **`Save`** 버튼 클릭

### ② (선택 사항) 로그인 ID/PW 비밀변수 등록 (보안 강화)
공개 리포지토리를 사용 중이셔서 ID/PW를 비공개로 감싸고 싶으시다면 설정합니다. (비공개 저장소라면 생략 가능)
1. **`Settings`** -> **`Secrets and variables`** -> **`Actions`** 클릭
2. **`New repository secret`** 버튼 클릭
3. 아래 표에 맞춰 변수를 생성해 입력합니다.
   * `Name`: **`KRX_ID`** / `Value`: 사용자 ID
   * `Name`: **`KRX_PW`** / `Value`: 사용자 패스워드

---
준비가 끝나면 GitHub 리포지토리의 **`Actions`** 탭으로 가서 **`Run 60-day New High Screener`** 워크플로우를 선택하고 **`Run workflow`**를 누르면 바로 가상 컴퓨터가 스크리닝을 시작하는 모습을 보실 수 있습니다.
