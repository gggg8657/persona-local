# 제3자 구성요소 (Third-Party Notices) — persona-local

이 저장소의 원저작물은 DongJu Kim(gggg8657)이 작성했다(`NOTICE`, `LICENSE`). 아래 제3자 구성요소는 각자의 라이선스를 따르며, 이 저장소의 MIT 라이선스로 바뀌지 않는다.
조사 기준: 2026-10-12, 저장소의 실제 파일(`app.py` import, `setup.sh`, `scripts/gen_faces.py`, `personas/`, `ui.html`). 라이선스는 패키지/모델 카드/GitHub LICENSE 에서 확인.

| 이름 | 버전 | 쓰임 | 라이선스 | 링크 | 상업 이용 | 비고 |
|---|---|---|---|---|---|---|
| Python 표준 라이브러리 (http.server, sqlite3 등) | 3.9+ | 설치(실행 환경) | PSF-2.0 (SQLite 는 public domain) | https://docs.python.org/3/license.html | 가능 | 앱은 표준 라이브러리만 씀 |
| Ollama | 미고정 | 외부 서비스(LLM 서버, `setup.sh` 가 없으면 설치) | MIT | https://github.com/ollama/ollama | 가능 | 설치 스크립트 `ollama.com/install.sh` |
| Google Gemma 4 `gemma4:31b` | — | 내려받는 가중치(포털 기본 LLM, Ollama pull) | Apache-2.0 | https://huggingface.co/google/gemma-4-31B-it | 가능 | Ollama manifest 의 license 와 HF 모델 카드 모두 Apache-2.0 |
| Qwen3 `qwen3:8b` (단독 실행 기본값), `qwen3:32b` | — | 내려받는 가중치(Ollama pull) | Apache-2.0 | https://huggingface.co/Qwen/Qwen3-8B | 가능 | |
| vLLM · LM Studio · llama.cpp | — | 외부 서비스(있으면 OpenAI 호환 API 로 탐색만) | 각자 | — | 해당 서버·모델 라이선스 따름 | 설치하지 않음 |
| `personas/*.png` (6장), `docs/img/chat.jpg` 의 얼굴 | 2026-10-06 생성 | 동봉(생성 이미지) | 생성 모델: CreativeML OpenRAIL-M 의 Output 조항 | `scripts/gen_faces.py` | **조건부** | AI 생성 가상 인물. 아래 "확인 필요" 참고 |
| Realistic Vision V5.1 (SG161222/Realistic_Vision_V5.1_noVAE) | V5.1 | 내려받는 가중치(`scripts/gen_faces.py` 만, 선택) | CreativeML OpenRAIL-M | https://huggingface.co/SG161222/Realistic_Vision_V5.1_noVAE | **조건부** (사용 제한 Attachment A) | 저장소에 넣지 않음. 학습 데이터 비공개 |
| stabilityai/sd-vae-ft-mse | — | 내려받는 가중치(`scripts/gen_faces.py` 만) | MIT | https://huggingface.co/stabilityai/sd-vae-ft-mse | 가능 | |
| diffusers | 미고정 | 설치(`scripts/gen_faces.py` 만, 선택) | Apache-2.0 | https://github.com/huggingface/diffusers | 가능 | |
| PyTorch | 미고정 | 설치(`scripts/gen_faces.py` 만, 선택) | BSD-3-Clause | https://github.com/pytorch/pytorch | 가능 | |
| tts-local · meeting-local · avatar-local | — | 외부 서비스(선택 연결) | 각 저장소 참고 | https://github.com/gggg8657 | 각 저장소 참고 | 같은 저작자의 별도 도구. avatar-local 은 자체 제3자 모델 조건이 있음 |

`ui.html` 은 외부 라이브러리·웹폰트를 쓰지 않는다(canvas·Web Audio, 시스템 글꼴).

## 확인 필요

- **[#1](https://github.com/gggg8657/persona-local/issues/1) Realistic Vision V5.1 생성 초상 — CreativeML OpenRAIL-M**: 동봉 초상 6장은 AI 생성 가상 인물이다. OpenRAIL-M §6 은 생성물에 권리를 주장하지 않지만 사용 책임과 사용 제한(Attachment A)이 사용자에게 있고, 학습 데이터가 공개돼 있지 않아 실존 인물과의 우연한 닮음(초상권)을 배제할 수 없다.
  회피: `personas/<이름>.png` 를 직접 그린 그림이나 라이선스가 분명한 일러스트로 바꾸면 된다(코드 변경 없음).
