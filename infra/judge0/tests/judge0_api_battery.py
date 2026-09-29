import base64, json, sys, time, urllib.request
J = "http://localhost:2358"
def sub(src, stdin="", expected=None, **lim):
    b = {"source_code": base64.b64encode(src.encode()).decode(), "language_id": 71,
         "stdin": base64.b64encode(stdin.encode()).decode(), "cpu_time_limit": 2, "wall_time_limit": 5,
         "memory_limit": 128000, **lim}
    if expected is not None: b["expected_output"] = base64.b64encode(expected.encode()).decode()
    req = urllib.request.Request(J + "/submissions?base64_encoded=true", data=json.dumps(b).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    tok = json.loads(urllib.request.urlopen(req, timeout=30).read())["token"]
    deadline = time.time() + 60
    while True:
        r = json.loads(urllib.request.urlopen(f"{J}/submissions/{tok}?base64_encoded=true", timeout=30).read())
        if r["status"]["id"] > 2: break
        if time.time() > deadline: raise TimeoutError("judge0 did not finish in 60s")
        time.sleep(0.5)
    out = base64.b64decode(r.get("stdout") or "").decode(errors="replace").strip()
    return r["status"]["description"], out, r.get("memory"), r.get("time")
T = [
 ("correct answer",       'import ast,sys\nn=ast.literal_eval(sys.stdin.read())\nprint(sum(n))', "[1,2,3]", "6",  lambda s,o: s=="Accepted"),
 ("wrong answer",         'print(5)', "", "6",                                                             lambda s,o: s=="Wrong Answer"),
 ("runtime error",        'raise ValueError("x")', "", None,                                            lambda s,o: s.startswith("Runtime Error")),
 ("syntax error",         'def (', "", None,                                                             lambda s,o: s.startswith("Runtime Error")),
 ("cpu infinite loop",    'while True: pass', "", None,                                                  lambda s,o: s=="Time Limit Exceeded"),
 ("wall sleep",           'import time; time.sleep(60)', "", None,                                       lambda s,o: s=="Time Limit Exceeded"),
 ("memory bomb 1GB",      'x=bytearray(1024**3); print("ALLOCATED")', "", None,                          lambda s,o: "ALLOCATED" not in o and s!="Accepted"),
 ("fork bomb",            'import os\nn=0\ntry:\n  while n<1000:\n    if os.fork()==0:\n      import time; time.sleep(3); os._exit(0)\n    n+=1\nexcept OSError: pass\nprint("capped" if n<1000 else "UNLIMITED", n)', "", None, lambda s,o: "UNLIMITED" not in o),
 ("network egress",       'import socket\ntry:\n  socket.create_connection(("1.1.1.1",53),timeout=2); print("CONNECTED")\nexcept OSError as e: print("blocked")', "", None, lambda s,o: o=="blocked"),
 ("read judge0 secrets",  'import os\nleak=[k for k in os.environ if any(w in k for w in ("PASS","SECRET","POSTGRES","REDIS"))]\nfs=[p for p in ("/api/.env","/api/config","/proc/1/environ") if os.path.exists(p) and os.access(p, os.R_OK)]\nprint("clean" if not leak and not fs else f"LEAK {leak} {fs}")', "", None, lambda s,o: o=="clean"),
 ("write outside box",    'ok=[]\nfor p in ("/usr/pwn","/api/pwn","/pwn"):\n  try: open(p,"w").write("x"); ok.append(p)\n  except OSError: pass\nprint("denied" if not ok else f"WROTE {ok}")', "", None, lambda s,o: o=="denied"),
 ("non-root + no setuid", 'import os\ntry: os.setuid(0); print("ROOT")\nexcept OSError: print("nonroot", os.getuid())', "", None, lambda s,o: o.startswith("nonroot") and "nonroot 0" not in o),
 ("output flood",         'import sys\nsys.stdout.write("x"*50_000_000)', "", None,                      lambda s,o: s!="Accepted" or len(o)<50_000_000),
]
p = f = 0
for name, src, stdin, exp, ok in T:
    s, o, m, t = sub(src, stdin, exp)
    good = ok(s, o); p += good; f += not good
    print(f"{'PASS' if good else 'FAIL'}  {name:22} status={s:24} mem={m}KB time={t}s out={o[:60]!r}")
# concurrency: 8 parallel submissions all judged correctly
import concurrent.futures as cf
with cf.ThreadPoolExecutor(8) as ex:
    res = list(ex.map(lambda i: sub(f'print({i}*{i})', "", str(i*i)), range(8)))
good = all(r[0] == "Accepted" for r in res); p += good; f += not good
print(f"{'PASS' if good else 'FAIL'}  8 concurrent submissions: {[r[0] for r in res]}")
print(f"RESULT: {p} passed, {f} failed"); sys.exit(1 if f else 0)
