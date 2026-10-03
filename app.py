#!/usr/bin/env python3
"""persona local — AI 캐릭터 대화 (개인 토이). 페르소나·기억(sqlite)·호감도·TTS. stdlib만.

  python3 app.py                                   # http://localhost:8776
  python3 app.py --cli gf "오늘 라멘 먹었어"
  TTS_BASE_URL=http://localhost:8771/v1 python3 app.py   # 🔊 버튼 활성

personas/*.md 한 파일 = 한 캐릭터 (frontmatter: name/title/avatar/voice/greeting, --- 뒤 = 시스템 프롬프트).
"""
import datetime
import json
import os
import re
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
HISTORY = 20          # ponytail: 최근 20턴만 모델에 넣음, 길어지면 요약 압축으로 승급
GREET_AFTER_H = 8


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


GOAL = read(os.path.join(ROOT, "goal-prompt.md"))


def load_personas():
    out = {}
    for fn in sorted(os.listdir(os.path.join(ROOT, "personas"))):
        if not fn.endswith(".md"):
            continue
        head, _, body = read(os.path.join(ROOT, "personas", fn)).partition("\n---\n")
        p = {k.strip(): v.strip() for k, _, v in (l.partition(":") for l in head.splitlines() if ":" in l)}
        for k in ("name", "title", "avatar", "greeting"):
            assert k in p, f"{fn}: {k} 없음"
        p["prompt"] = body.strip()
        out[p["name"]] = p
    return out


PERSONAS = load_personas()


# ── DB ──────────────────────────────────────────────────────────────────
def db():
    os.makedirs(WS, exist_ok=True)
    c = sqlite3.connect(os.path.join(WS, "persona.db"), timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, persona TEXT, role TEXT, content TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS facts(persona TEXT, key TEXT, value TEXT, ts TEXT, PRIMARY KEY(persona, key));
    CREATE TABLE IF NOT EXISTS stats(persona TEXT PRIMARY KEY, affinity INTEGER DEFAULT 0, turns INTEGER DEFAULT 0, last_ts TEXT);""")
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


def tts(text, voice):
    body = {"model": "tts", "input": text, "voice": voice or "KR", "response_format": "mp3"}
    with urllib.request.urlopen(urllib.request.Request(TTS + "/audio/speech", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=600) as r:
        return r.read()


# ── HTTP ────────────────────────────────────────────────────────────────
HTML = read(os.path.join(ROOT, "ui.html"))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if p == "/api/models":
                return self._send(models())
            if p == "/api/personas":
                c = db()
                return self._send([{k: v for k, v in x.items() if k != "prompt"} | {"stat": stat(c, x["name"])} for x in PERSONAS.values()])
            m = re.fullmatch(r"/api/state/(\w+)", p)
            if m and m.group(1) in PERSONAS:
                c = db()
                return self._send({"history": history(c, m.group(1), 200), "facts": facts(c, m.group(1)), "stat": stat(c, m.group(1)),
                                   "greet": greet(m.group(1)), "tts": bool(TTS)})
            self._send(HTML.replace("%MODEL%", json.dumps(MODEL)).encode(), "text/html; charset=utf-8")
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
            c = db()
            persona = req.get("persona", "")
            if persona not in PERSONAS:
                return self._send({"error": "없는 페르소나"}, code=400)
            with c:
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
    print(f"persona local → http://localhost:{PORT}  (model={MODEL}, llm={LLM_API} {LLM_BASE}, tts={TTS or '없음'}, personas={len(PERSONAS)})")
    ThreadingHTTPServer(("", PORT), H).serve_forever()
