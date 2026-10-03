# persona-local — AI 캐릭터 대화 (개인 토이)

> **한 줄 요약** — 로컬 LLM에 페르소나·기억·호감도·음성을 붙인 캐릭터 채팅. 여자친구/남자친구/선배 멘토/모의 면접관/영어 회화 파트너/츤데레 친구 6종.
> **개인 토이 프로젝트**입니다. 사내 에이전트 포털에는 노출하지 않습니다(tools.json `hidden`). 파이썬 표준 라이브러리 + sqlite, 외부 통신 없음.

```bash
bash setup.sh                     # LLM 탐색 → selftest → http://localhost:8776
python3 app.py --cli gf "나 오늘 라멘 먹었어"
TTS_BASE_URL=http://localhost:8771/v1 python3 app.py   # tts-local 이 떠 있으면 🔊 버튼
```

| 환경변수 | 기본 | 설명 |
|---|---|---|
| `LLM_API` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | ollama / :11434 / qwen3:8b | 다른 패키지와 동일 규약 |
| `TTS_BASE_URL` | (없음) | OpenAI 호환 `/v1/audio/speech` (tts-local) |
| `WORKSPACE` | `_workspace/` | `persona.db`(대화·기억·호감도) 위치. 포털이 `AGENT_DATA/persona-local` 로 지정 |
| `PORT` | 8776 | |

## 동작
- **페르소나**: `personas/*.md` 한 파일 = 한 캐릭터(frontmatter name/title/avatar/voice/greeting, `---` 아래가 시스템 프롬프트). 파일 추가하면 끝.
- **기억**: 매 턴 뒤 작은 2차 콜로 사용자에 대한 사실(이름·취향·일정…)을 `key=value` 로 뽑아 저장하고, 다음 턴 시스템 프롬프트에 `[기억]` 으로 넣음. 오른쪽 패널에서 수정·삭제.
- **호감도**: 턴마다 +1(최대 100), 카드의 바. 재미용.
- **먼저 인사**: 8시간 넘게 안 보면 기억 하나를 언급하며 먼저 말을 겁니다.
- **말투·길이 슬라이더**, 모델 선택, 대화 초기화(기억은 유지).

## 한계
- 최근 20턴만 모델에 들어감(요약 압축 없음). 8B 모델은 캐릭터가 가끔 흔들림 → 큰 모델 권장.
- 사실 추출은 LLM 판단이라 엉뚱한 기억이 들어올 수 있음 → 패널에서 지우면 됨.
