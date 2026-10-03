#!/usr/bin/env python3
"""LLM 없이: 페르소나 로드 → 대화 2턴(기억 추출·주입·호감도) → CLI → ui 상대경로.  python3 selftest.py"""
import os, subprocess, sys, tempfile
os.environ["WORKSPACE"] = tempfile.mkdtemp()
import app

calls = []
def fake(messages, model=None, on_token=None, temperature=0.8):
    calls.append(messages)
    if messages[0]["role"] == "user":          # 기억 추출 콜
        return "이름=동주\n좋아하는 음식=라멘\n없음"
    out = "응, 라멘 좋지. 오늘 어땠어?"
    if on_token: on_token(out)
    return out
app.llm = fake

assert len(app.PERSONAS) == 6 and all(k in app.PERSONAS[n] for n in app.PERSONAS for k in ("title", "avatar", "greeting", "prompt"))
r = app.chat("gf", "나 동주야, 오늘 라멘 먹었어", "fake")
assert r["reply"].startswith("응") and r["stat"]["affinity"] == 1 and r["stat"]["turns"] == 1
assert {f["key"]: f["value"] for f in r["facts"]} == {"이름": "동주", "좋아하는 음식": "라멘"}, r["facts"]
r2 = app.chat("gf", "그래서 말인데", "fake")
sysmsg = calls[-2][0]["content"]                 # 2턴째 대화 콜의 system
assert "[기억] 이름=동주; 좋아하는 음식=라멘" in sysmsg and "서연" in sysmsg
assert [m["role"] for m in calls[-2][1:]] == ["user", "assistant", "user"] and r2["stat"]["affinity"] == 2
with app.db() as c:
    assert len(app.history(c, "gf")) == 4 and app.stat(c, "gf")["affinity"] == 2
    c.execute("UPDATE stats SET last_ts='2020-01-01T00:00:00'")
g = app.greet("gf", "fake")                      # 8시간 지남 + 기억 있음 → LLM 인사
assert g and app.greet("gf", "fake") is None      # 방금 인사했으니 다시 안 함
assert "/api/" not in open(os.path.join(app.ROOT, "ui.html"), encoding="utf-8").read().replace("'api/", "")
assert "api/" in open(os.path.join(app.ROOT, "ui.html"), encoding="utf-8").read()
try: app.chat("nope", "x"); raise SystemExit("없는 페르소나는 거부돼야 함")
except ValueError: pass
print("selftest OK — personas:", ", ".join(app.PERSONAS))
