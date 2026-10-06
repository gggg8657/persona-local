#!/usr/bin/env python3
"""persona local — AI 캐릭터 대화 (개인 토이). 페르소나·기억(sqlite)·호감도·TTS. stdlib만.

  python3 app.py                                   # http://localhost:8776
  python3 app.py --cli gf "오늘 라멘 먹었어"
  TTS_BASE_URL=http://localhost:8771/v1 python3 app.py   # 🔊 버튼 활성

personas/*.md 한 파일 = 한 캐릭터 (frontmatter: name/title/avatar/voice/greeting, --- 뒤 = 시스템 프롬프트).
"""
import base64
import datetime
import json
import os
import re
import secrets
import sqlite3
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("WORKSPACE") or os.path.join(ROOT, "_workspace")  # 포털이 AGENT_DATA/<도구> 로 모아 줌
LLM_API = os.environ.get("LLM_API", "ollama")
LLM_BASE = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1" if LLM_API == "openai" else "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")
LLM_KEY = os.environ.get("LLM_API_KEY", "")
NUM_CTX = int(os.environ.get("NUM_CTX", "8192"))
PORT = int(os.environ.get("PORT", "8776"))
TTS = os.environ.get("TTS_BASE_URL", "").rstrip("/")
STT = os.environ.get("STT_BASE_URL", "http://localhost:8767/v1").rstrip("/")     # meeting-local 의 /v1/audio/transcriptions
AVATAR = os.environ.get("AVATAR_URL", "http://localhost:8777/api/run")           # avatar-local (고화질 클립, 선택)
HISTORY = 20          # ponytail: 최근 20턴만 모델에 넣음, 길어지면 요약 압축으로 승급
GREET_AFTER_H = 8


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


GOAL = read(os.path.join(ROOT, "goal-prompt.md"))


def persona_dirs():
    """기본 캐릭터(저장소 personas/) + 사용자가 만든 캐릭터(데이터 폴더 personas/ — avatar 스튜디오에서 추가)"""
    return [os.path.join(ROOT, "personas"), os.path.join(WS, "personas")]


def load_personas():
    out = {}
    for d in persona_dirs():
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not fn.endswith(".md"):
                continue
            head, _, body = read(os.path.join(d, fn)).partition("\n---\n")
            p = {k.strip(): v.strip() for k, _, v in (l.partition(":") for l in head.splitlines() if ":" in l)}
            for k in ("name", "title", "avatar", "greeting"):
                assert k in p, f"{fn}: {k} 없음"
            p["prompt"] = body.strip(); p["dir"] = d
            out[p["name"]] = p
    return out


def img_path(name):
    return os.path.join(PERSONAS[name]["dir"] if name in PERSONAS else os.path.join(ROOT, "personas"), name + ".png")


def persona_new(req):
    """avatar 스튜디오가 만든 캐릭터를 받아 새 페르소나로: LLM 이 성격 설명으로 설정(제목·첫인사·시스템 프롬프트)을 쓴다"""
    name, personality = (req.get("name") or "").strip()[:20], (req.get("personality") or "").strip()
    if not name: raise ValueError("이름이 비었습니다")
    out = "".join(llm([{"role": "system", "content": "캐릭터 대화 앱의 캐릭터 설정을 쓴다. JSON 하나만: "
                        '{"title": "한 줄 소개(10자 안팎)", "avatar": "이모지 하나", "greeting": "처음 건네는 말 한 문장", '
                        '"prompt": "너는 …다. 로 시작하는 시스템 프롬프트 3~5문장: 이름·나이·직업·성격·말투(반말/존댓말)·사용자를 부르는 호칭·대화 방식"}'},
                       {"role": "user", "content": f"[이름] {name}\n[생김새] {req.get('look', '')}\n[성격·관계] {personality or '친근한 대화 상대'}"}],
                      temperature=0.5))
    m = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", out, flags=re.S), re.S)
    if not m: raise RuntimeError("캐릭터 설정을 만들지 못했습니다: " + out[:200])
    j = json.loads(m.group(0))
    slug = "c" + secrets.token_hex(3)
    d = os.path.join(WS, "personas"); os.makedirs(d, exist_ok=True)
    one = lambda s: str(s or "").replace("\n", " ").strip()
    with open(os.path.join(d, slug + ".md"), "w", encoding="utf-8") as f:
        f.write(f"name: {slug}\ntitle: {one(j.get('title')) or name}\navatar: {one(j.get('avatar')) or '🙂'}\nvoice: KR\n"
                f"greeting: {one(j.get('greeting')) or '안녕!'}\n---\n{str(j.get('prompt') or '').strip()}\n")
    with open(os.path.join(d, slug + ".png"), "wb") as f:
        f.write(base64.b64decode(req["image_b64"]))
    PERSONAS.clear(); PERSONAS.update(load_personas())
    mo = req.get("mouth")
    if mo:
        c = db()
        with c:
            c.execute("INSERT OR REPLACE INTO mouth VALUES(?,?,?,?)", (slug, float(mo["x"]), float(mo["y"]), float(mo.get("w", 0.08))))
    return {"name": slug, "title": PERSONAS[slug]["title"]}


PERSONAS = load_personas()


# ── DB ──────────────────────────────────────────────────────────────────
def db():
    os.makedirs(WS, exist_ok=True)
    c = sqlite3.connect(os.path.join(WS, "persona.db"), timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, persona TEXT, role TEXT, content TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS facts(persona TEXT, key TEXT, value TEXT, ts TEXT, PRIMARY KEY(persona, key));
    CREATE TABLE IF NOT EXISTS stats(persona TEXT PRIMARY KEY, affinity INTEGER DEFAULT 0, turns INTEGER DEFAULT 0, last_ts TEXT);
    CREATE TABLE IF NOT EXISTS mouth(persona TEXT PRIMARY KEY, x REAL, y REAL, w REAL);""")
    return c


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def facts(c, persona):
    return [dict(r) for r in c.execute("SELECT key, value, ts FROM facts WHERE persona=? ORDER BY ts", (persona,))]


def history(c, persona, n=HISTORY):
    rows = c.execute("SELECT role, content, ts FROM messages WHERE persona=? ORDER BY id DESC LIMIT ?", (persona, n)).fetchall()
    return [dict(r) for r in reversed(rows)]


def stat(c, persona):
    r = c.execute("SELECT affinity, turns, last_ts FROM stats WHERE persona=?", (persona,)).fetchone()
    return dict(r) if r else {"affinity": 0, "turns": 0, "last_ts": None}


# ── LLM ────────────────────────────────────────────────────────────────
def _clean(out):
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def _hdr():
    return {"Content-Type": "application/json", **({"Authorization": f"Bearer {LLM_KEY}"} if LLM_KEY else {})}


def llm(messages, model=MODEL, on_token=None, temperature=0.8):
    """messages=[{role,content}...] 스트리밍. Ollama 네이티브 또는 OpenAI 호환."""
    buf = []

    def take(tok):
        if tok:
            buf.append(tok)
            if on_token:
                on_token(tok)

    if LLM_API == "openai":
        body = {"model": model, "stream": True, "temperature": temperature, "messages": messages}
        req = urllib.request.Request(LLM_BASE + "/chat/completions", json.dumps(body).encode(), _hdr())
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                for line in r:
                    line = line.decode().strip()
                    if line.startswith("data:") and line != "data: [DONE]":
                        take((json.loads(line[5:])["choices"][0].get("delta") or {}).get("content") or "")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"LLM HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        return _clean("".join(buf))
    body = {"model": model, "stream": True, "think": False, "options": {"temperature": temperature, "num_ctx": NUM_CTX}, "messages": messages}
    for attempt in (0, 1):
        try:
            req = urllib.request.Request(LLM_BASE + "/api/chat", json.dumps(body).encode(), _hdr())
            with urllib.request.urlopen(req, timeout=3600) as r:
                for line in r:
                    if line.strip():
                        j = json.loads(line)
                        if "error" in j:
                            raise RuntimeError(j["error"])
                        take(j.get("message", {}).get("content", ""))
                        if j.get("done"):
                            break
            return _clean("".join(buf))
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            if attempt == 0 and "think" in msg:
                body.pop("think")
                continue
            raise RuntimeError(f"Ollama HTTP {e.code}: {msg[:300]}")


def models():
    if LLM_API == "openai":
        with urllib.request.urlopen(urllib.request.Request(LLM_BASE + "/models", headers=_hdr()), timeout=10) as r:
            return [m["id"] for m in json.load(r)["data"]]
    with urllib.request.urlopen(LLM_BASE + "/api/tags", timeout=10) as r:
        return [m["name"] for m in json.load(r)["models"]]


# ── 대화 ────────────────────────────────────────────────────────────────
TONES = {0: "말투: 담백하고 차분하게.", 1: "", 2: "말투: 애교 있고 살갑게, 감탄사·웃음 조금."}
LENS = {0: "한 번에 1~2문장.", 1: "", 2: "한 번에 4~6문장, 조금 더 길게."}


def system_prompt(c, persona, tone=1, length=1):
    p = PERSONAS[persona]
    fs = facts(c, persona)
    mem = "\n[기억] " + "; ".join(f"{f['key']}={f['value']}" for f in fs) if fs else "\n[기억] 아직 없음"
    return "\n".join(x for x in (GOAL, p["prompt"], TONES.get(int(tone), ""), LENS.get(int(length), ""), mem) if x)


MULTI = {"취향", "좋아하는 것", "싫어하는 것", "관심사", "취미", "일정", "가족", "기분", "고민", "목표"}  # 값이 여러 개 쌓이는 기억 항목


def extract_facts(c, persona, user_text, reply, model):
    """2차 콜: 사용자에 대한 새 사실 0~3개 'key=value' 줄 → facts upsert. 실패해도 대화는 멀쩡해야 한다."""
    known = "; ".join(f"{f['key']}={f['value']}" for f in facts(c, persona)) or "없음"
    prompt = (f"아래는 사용자의 말이다. 사용자 자신에 대한 새로운 사실(이름, 직업, 취향, 일정, 가족, 기분의 원인 등)만 'key=value' 한 줄씩 최대 3줄로 적어라. "
              f"이미 아는 것({known})과 겹치거나 사실이 없으면 '없음'이라고만 써라. 설명 금지.\n\n사용자: {user_text}")
    try:
        out = llm([{"role": "user", "content": prompt}], model, temperature=0.1)
    except Exception:
        return []
    new = []
    for line in out.splitlines():
        m = re.match(r"\s*[-*]?\s*([^=:\n]{1,20})\s*[=:]\s*(.{1,80})$", line.strip())
        if m and m.group(1).strip() not in ("없음",) and "없음" != m.group(2).strip():
            k, v = m.group(1).strip(), m.group(2).strip().rstrip(".。")
            old = c.execute("SELECT value FROM facts WHERE persona=? AND key=?", (persona, k)).fetchone()
            if old and k in MULTI and v not in old[0]:  # 취향·일정처럼 여러 개 쌓이는 항목은 덧붙인다(덮어쓰면 앞의 것이 사라짐)
                v = (old[0] + ", " + v)[-120:]
            c.execute("INSERT OR REPLACE INTO facts VALUES(?,?,?,?)", (persona, k, v, now()))
            new.append({"key": k, "value": v})
    return new[:3]


def chat(persona, text, model=MODEL, tone=1, length=1, emit=lambda ev: None):
    if persona not in PERSONAS:
        raise ValueError("없는 페르소나")
    text = text.strip()
    if not text:
        raise ValueError("빈 메시지")
    c = db()
    with c:
        c.execute("INSERT INTO messages(persona,role,content,ts) VALUES(?,?,?,?)", (persona, "user", text, now()))
        msgs = [{"role": "system", "content": system_prompt(c, persona, tone, length)}] + \
               [{"role": m["role"], "content": m["content"]} for m in history(c, persona)]
    reply = llm(msgs, model, on_token=lambda t: emit({"token": t}))
    with c:
        c.execute("INSERT INTO messages(persona,role,content,ts) VALUES(?,?,?,?)", (persona, "assistant", reply, now()))
        c.execute("INSERT INTO stats(persona,affinity,turns,last_ts) VALUES(?,1,1,?) ON CONFLICT(persona) DO UPDATE SET "
                  "affinity=MIN(100, affinity+1), turns=turns+1, last_ts=excluded.last_ts", (persona, now()))
        new = extract_facts(c, persona, text, reply, model)
    return {"reply": reply, "new_facts": new, "stat": stat(c, persona), "facts": facts(c, persona)}


def greet(persona, model=MODEL):
    """8시간 넘게 안 봤으면 먼저 인사 (기억이 있으면 그걸 끌어서). 반환: 인사 문자열 또는 None"""
    c = db()
    s = stat(c, persona)
    if s["last_ts"] and (datetime.datetime.now() - datetime.datetime.fromisoformat(s["last_ts"])).total_seconds() < GREET_AFTER_H * 3600:
        return None
    p = PERSONAS[persona]
    fs = facts(c, persona)
    if not fs:
        g = p["greeting"]
    else:
        try:
            g = llm([{"role": "system", "content": system_prompt(c, persona)},
                     {"role": "user", "content": "(상대가 오랜만에 들어왔다. 기억 중 하나를 자연스럽게 언급하며 먼저 인사해라. 2문장.)"}], model)
        except Exception:
            g = p["greeting"]
    with c:
        c.execute("INSERT INTO messages(persona,role,content,ts) VALUES(?,?,?,?)", (persona, "assistant", g, now()))
        c.execute("INSERT INTO stats(persona,affinity,turns,last_ts) VALUES(?,0,0,?) ON CONFLICT(persona) DO UPDATE SET last_ts=excluded.last_ts", (persona, now()))
    return g


def stt(audio_b64):
    """STT_BASE_URL 로 전달 (JSON base64). 반환 text."""
    req = urllib.request.Request(STT + "/audio/transcriptions", json.dumps({"file": audio_b64}).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r).get("text", "")


def up(url):
    try:
        urllib.request.urlopen(url, timeout=1.5); return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def tts(text, voice):
    body = {"model": "tts", "input": text, "voice": voice or "KR", "response_format": "mp3"}
    with urllib.request.urlopen(urllib.request.Request(TTS + "/audio/speech", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=600) as r:
        return r.read()


# ── HTTP ────────────────────────────────────────────────────────────────
HTML = read(os.path.join(ROOT, "ui.html"))

# ── 저작권 표기 (LICENSE·NOTICE 참고) ─────────────────────────────────────
_SIG = __import__("base64").b64decode("wqkgMjAyNiBnZ2dnODY1NyDCtyBkb25nanVraW0uZGV2QGdtYWlsLmNvbQ==").decode()
_SIG_A = __import__("base64").b64decode("Z2dnZzg2NTcgPGRvbmdqdWtpbS5kZXZAZ21haWwuY29tPg==").decode()


def signed(html):
    """화면에 저작권 표기를 붙인다. ui.html 에서 지워져도 서버가 내보낼 때 다시 붙는다."""
    name, mail = _SIG.split(" · ")
    if 'name="author"' not in html:
        meta = f'<meta name="author" content="{name[7:]} <{mail}>">'
        html = html.replace("<head>", "<head>" + meta, 1) if "<head>" in html else meta + html
    if "data-sig" not in html:
        tag = (f'<!-- {_SIG} --><div data-sig title="{mail}" style="text-align:center;font-size:11px;color:#9aa0a6;'
               f'opacity:.55;margin:28px 0 8px">{name}</div>')
        html = html.replace("</body>", tag + "</body>", 1) if "</body>" in html else html + tag
    return html


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("X-Author", _SIG_A); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if self.path.startswith("/api/clip/"):  # avatar-local 결과 영상 중계
                rid = self.path.rsplit("/", 1)[1]
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]+", rid): raise ValueError("잘못된 클립 ID")
                with urllib.request.urlopen(AVATAR.rsplit("/api", 1)[0] + f"/api/runs/{rid}/final.mp4", timeout=60) as r:
                    return self._send(r.read(), "video/mp4")
            if p == "/api/models":
                return self._send(models())
            if p == "/api/personas":
                c = db()
                return self._send([{k: v for k, v in x.items() if k != "prompt"} | {"stat": stat(c, x["name"])} for x in PERSONAS.values()])
            m = re.fullmatch(r"/api/state/(\w+)", p)
            if m and m.group(1) in PERSONAS:
                c = db()
                mouth = c.execute("SELECT x,y,w FROM mouth WHERE persona=?", (m.group(1),)).fetchone()
                return self._send({"history": history(c, m.group(1), 200), "facts": facts(c, m.group(1)), "stat": stat(c, m.group(1)),
                                   "greet": greet(m.group(1)), "tts": bool(TTS), "stt": up(STT + "/models"), "avatar": up(AVATAR.rsplit("/api", 1)[0] + "/"),
                                   "mouth": dict(mouth) if mouth else None, "image": os.path.exists(img_path(m.group(1)))})
            m = re.fullmatch(r"/api/image/(\w+)", p)
            if m and m.group(1) in PERSONAS:
                with open(img_path(m.group(1)), "rb") as f:
                    return self._send(f.read(), "image/png")
            self._send(signed(HTML.replace("%MODEL%", json.dumps(MODEL))).encode(), "text/html; charset=utf-8")
        except Exception as e:
            self._send({"error": f"{type(e).__name__}: {e}"}, code=500)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        p = self.path.split("?")[0]
        try:
            if p == "/api/chat":
                self.send_response(200); self.send_header("Content-Type", "text/event-stream; charset=utf-8"); self.send_header("Cache-Control", "no-cache"); self.end_headers()

                def emit(ev):
                    self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()); self.wfile.flush()
                try:
                    emit({"done": chat(req.get("persona", ""), req.get("text", ""), req.get("model") or MODEL, req.get("tone", 1), req.get("length", 1), emit)})
                except Exception as e:
                    emit({"error": f"{type(e).__name__}: {e}"})
                return
            if p == "/api/persona_new":  # avatar 스튜디오 → 새 캐릭터
                return self._send(persona_new(req))
            if p == "/api/stt":
                if not req.get("audio"):
                    raise ValueError("audio 없음")
                return self._send({"text": stt(req["audio"])})
            c = db()
            persona = req.get("persona", "")
            if persona not in PERSONAS:
                return self._send({"error": "없는 페르소나"}, code=400)
            if p == "/api/avatar":  # 고화질 클립: avatar-local 에 그대로 넘기고 run_id 만 돌려줌 (영상은 avatar-local 에서 재생)
                with open(img_path(persona), "rb") as f:
                    body = {"photo_b64": base64.b64encode(f.read()).decode(), "photo_name": persona + ".png", "text": req.get("text", ""), "consent": True}
                r = urllib.request.urlopen(urllib.request.Request(AVATAR, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=3600)
                run_id = None
                for line in r:
                    if line.startswith(b"data: "):
                        ev = json.loads(line[6:])
                        if "error" in ev:
                            raise RuntimeError(ev["error"])
                        if "done" in ev:
                            run_id = ev["done"]["run_id"]
                if not run_id:
                    raise RuntimeError("avatar-local 이 결과 없이 끝났습니다")
                return self._send({"run_id": run_id, "video": f"api/clip/{run_id}"})  # 영상은 persona 가 중계 — 포털(8700)만 열린 사용자도 재생
            with c:
                if p == "/api/mouth":
                    c.execute("INSERT OR REPLACE INTO mouth VALUES(?,?,?,?)", (persona, float(req["x"]), float(req["y"]), float(req.get("w", 0.08))))
                    return self._send({"ok": True})
                if p == "/api/fact":
                    if not req.get("key"):
                        raise ValueError("key 없음")
                    c.execute("INSERT OR REPLACE INTO facts VALUES(?,?,?,?)", (persona, req["key"].strip()[:20], (req.get("value") or "").strip()[:80], now()))
                elif p == "/api/fact_del":
                    c.execute("DELETE FROM facts WHERE persona=? AND key=?", (persona, req.get("key", "")))
                elif p == "/api/reset":
                    c.execute("DELETE FROM messages WHERE persona=?", (persona,))
                    c.execute("DELETE FROM stats WHERE persona=?", (persona,))
                elif p == "/api/tts":
                    if not TTS:
                        return self._send({"error": "TTS 미연결"}, code=400)
                    return self._send(tts(req.get("text", ""), PERSONAS[persona].get("voice")), "audio/mpeg")
                else:
                    return self._send({"error": "not found"}, code=404)
            self._send({"facts": facts(c, persona)})
        except (ValueError, KeyError) as e:
            self._send({"error": str(e)}, code=400)
        except Exception as e:
            self._send({"error": f"{type(e).__name__}: {e}"}, code=500)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        who, text = sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""
        g = greet(who)
        if g:
            print(f"[{PERSONAS[who]['title']}] {g}")
        r = chat(who, text, emit=lambda ev: print(ev["token"], end="", flush=True) if "token" in ev else None)
        print(f"\n(호감도 {r['stat']['affinity']}" + (f" · 새 기억 {', '.join(f['key'] for f in r['new_facts'])}" if r["new_facts"] else "") + ")")
        sys.exit(0)
    print(f"persona local → http://localhost:{PORT}  (model={MODEL}, llm={LLM_API} {LLM_BASE}, tts={TTS or '없음'}, stt={STT}, personas={len(PERSONAS)})  {_SIG}")
    ThreadingHTTPServer(("", PORT), H).serve_forever()
