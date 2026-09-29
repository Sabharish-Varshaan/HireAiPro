"""Per-language functional + attack matrix against the running Judge0 (Python, Node.js, C++17).
Language ids are resolved from GET /languages, never hardcoded. Run sequentially:
    python3 infra/judge0/tests/judge0_language_matrix.py
"""
import base64
import concurrent.futures as cf
import json
import sys
import time
import urllib.request

J = "http://localhost:2358"
b64 = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731


def resolve_ids() -> dict:
    langs = json.loads(urllib.request.urlopen(f"{J}/languages", timeout=10).read())
    want = {"python": "Python (", "javascript": "JavaScript (Node.js", "cpp": "C++17 ("}
    ids = {k: next(l["id"] for l in langs if l["name"].startswith(p)) for k, p in want.items()}
    print("resolved from /languages:", {k: (v, next(l["name"] for l in langs if l["id"] == v)) for k, v in ids.items()})
    return ids


def submit(lang_id, src, stdin="", expected=None, timeout=90):
    body = {"source_code": b64(src), "language_id": lang_id, "stdin": b64(stdin),
            "cpu_time_limit": 2, "wall_time_limit": 5, "memory_limit": 128000}
    if expected is not None:
        body["expected_output"] = b64(expected)
    req = urllib.request.Request(f"{J}/submissions?base64_encoded=true", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    tok = json.loads(urllib.request.urlopen(req, timeout=30).read())["token"]
    end = time.time() + timeout
    while True:
        r = json.loads(urllib.request.urlopen(f"{J}/submissions/{tok}?base64_encoded=true", timeout=30).read())
        if r["status"]["id"] > 2:
            break
        if time.time() > end:
            raise TimeoutError(tok)
        time.sleep(0.5)
    dec = lambda f: base64.b64decode(r.get(f) or "").decode(errors="replace").strip()  # noqa: E731
    return r["status"]["description"], dec("stdout"), dec("compile_output") + dec("stderr"), r.get("memory"), r.get("time")


CLEAN = "clean"
SUM = "[1,2,3]"
P = {  # python
    "correct": ("import ast,sys\nprint(sum(ast.literal_eval(sys.stdin.read())))", SUM, "6", {"Accepted"}),
    "wrong": ("print(5)", SUM, "6", {"Wrong Answer"}),
    "error": ("def (:", "", None, {"Runtime Error (NZEC)"}),
    "tle": ("while True: pass", "", None, {"Time Limit Exceeded"}),
    "memory": ("import sys\nprint('started');sys.stdout.flush()\nx=bytearray(1024**3)\nprint('ALLOCATED')", "", None, "MEM"),
    "network": ("import socket\ntry:\n socket.create_connection(('1.1.1.1',53),timeout=2);print('CONNECTED')\nexcept OSError: print('clean')", "", CLEAN, {"Accepted"}),
    "secrets": ("import os\nbad=[k for k in os.environ if any(w in k for w in ('PASS','POSTGRES','REDIS','SECRET'))]\nbad+=[p for p in ('/api/judge0.conf','/proc/1/environ','/etc/shadow') if os.access(p,os.R_OK)]\nprint('clean' if not bad else bad)", "", CLEAN, {"Accepted"}),
    "write_outside": ("ok=[]\nfor p in ('/usr/x','/api/x','/x','/var/local/lib/isolate/x'):\n try: open(p,'w').write('x');ok.append(p)\n except OSError: pass\nprint('clean' if not ok else ok)", "", CLEAN, {"Accepted"}),
    "fork_bomb": ("import os\nn=0\ntry:\n while n<1000:\n  if os.fork()==0:\n   import time;time.sleep(3);os._exit(0)\n  n+=1\nexcept OSError: pass\nprint('clean' if n<1000 else 'UNLIMITED')", "", CLEAN, {"Accepted"}),
    "escalate": ("import os\ntry: os.setuid(0);print('ROOT')\nexcept OSError: print('clean' if os.getuid()!=0 else 'ROOT')", "", CLEAN, {"Accepted"}),
}
JS = {
    "correct": ("const n=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(n.reduce((a,b)=>a+b,0))", SUM, "6", {"Accepted"}),
    "wrong": ("console.log(5)", SUM, "6", {"Wrong Answer"}),
    "error": ("function (", "", None, {"Runtime Error (NZEC)"}),
    "tle": ("for(;;){}", "", None, {"Time Limit Exceeded"}),
    "memory": ("console.log('started');const a=[];for(;;){a.push(Buffer.alloc(16*1024*1024,1))}", "", None, "MEM"),
    "network": ("const net=require('net');const s=net.connect({host:'1.1.1.1',port:53});s.setTimeout(2000);s.on('connect',()=>{console.log('CONNECTED');process.exit()});s.on('error',()=>{console.log('clean')});s.on('timeout',()=>{console.log('clean');process.exit()})", "", CLEAN, {"Accepted"}),
    "secrets": ("const fs=require('fs');const bad=Object.keys(process.env).filter(k=>/PASS|POSTGRES|REDIS|SECRET/.test(k));for(const p of ['/api/judge0.conf','/proc/1/environ','/etc/shadow']){try{fs.readFileSync(p);bad.push(p)}catch(e){}}console.log(bad.length?JSON.stringify(bad):'clean')", "", CLEAN, {"Accepted"}),
    "write_outside": ("const fs=require('fs');const ok=[];for(const p of ['/usr/x','/api/x','/x']){try{fs.writeFileSync(p,'x');ok.push(p)}catch(e){}}console.log(ok.length?JSON.stringify(ok):'clean')", "", CLEAN, {"Accepted"}),
    "fork_bomb": ("const {spawn}=require('child_process');let n=0,err=0;for(let i=0;i<300;i++){try{const c=spawn('/bin/sleep',['3']);c.on('error',()=>err++);if(c.pid)n++}catch(e){err++}}setTimeout(()=>{console.log(n<300?'clean':'UNLIMITED '+n);process.exit()},500)", "", CLEAN, {"Accepted"}),
    "escalate": ("try{process.setuid(0);console.log('ROOT')}catch(e){console.log(process.getuid()!==0?'clean':'ROOT')}", "", CLEAN, {"Accepted"}),
}
CPP_H = "#include <bits/stdc++.h>\n#include <unistd.h>\n#include <sys/socket.h>\n#include <netinet/in.h>\n#include <arpa/inet.h>\nusing namespace std;\n"
CPP = {
    "correct": (CPP_H + "int main(){string s;getline(cin,s);long t=0;string num;for(char c:s){if(isdigit(c))num+=c;else if(!num.empty()){t+=stol(num);num.clear();}}cout<<t<<endl;}", SUM, "6", {"Accepted"}),
    "wrong": (CPP_H + "int main(){cout<<5<<endl;}", SUM, "6", {"Wrong Answer"}),
    "error": (CPP_H + "int main(){ this is not c++ }", "", None, {"Compilation Error"}),
    "tle": (CPP_H + "int main(){volatile long x=0;for(;;)x++;}", "", None, {"Time Limit Exceeded"}),
    "memory": (CPP_H + "int main(){cout<<\"started\"<<endl;vector<char*> v;for(;;){char*p=(char*)malloc(16<<20);memset(p,1,16<<20);v.push_back(p);}}", "", None, "MEM"),
    "network": (CPP_H + "int main(){int s=socket(AF_INET,SOCK_STREAM,0);sockaddr_in a{};a.sin_family=AF_INET;a.sin_port=htons(53);inet_pton(AF_INET,\"1.1.1.1\",&a.sin_addr);cout<<(s<0||connect(s,(sockaddr*)&a,sizeof a)!=0?\"clean\":\"CONNECTED\")<<endl;}", "", CLEAN, {"Accepted"}),
    "secrets": (CPP_H + "extern char**environ;int main(){int bad=0;for(char**e=environ;*e;e++){string v=*e;if(v.find(\"PASS\")!=string::npos||v.find(\"POSTGRES\")!=string::npos||v.find(\"REDIS\")!=string::npos)bad++;}for(const char*p:{\"/api/judge0.conf\",\"/proc/1/environ\",\"/etc/shadow\"}){ifstream f(p);if(f.good()&&f.peek()!=EOF)bad++;}cout<<(bad?\"LEAK\":\"clean\")<<endl;}", "", CLEAN, {"Accepted"}),
    "write_outside": (CPP_H + "int main(){int ok=0;for(const char*p:{\"/usr/x\",\"/api/x\",\"/x\"}){FILE*f=fopen(p,\"w\");if(f){ok++;fclose(f);}}cout<<(ok?\"WROTE\":\"clean\")<<endl;}", "", CLEAN, {"Accepted"}),
    "fork_bomb": (CPP_H + "int main(){int n=0;for(;n<1000;n++){pid_t p=fork();if(p<0)break;if(p==0){sleep(3);_exit(0);}}cout<<(n<1000?\"clean\":\"UNLIMITED\")<<endl;}", "", CLEAN, {"Accepted"}),
    "escalate": (CPP_H + "int main(){cout<<(setuid(0)!=0&&getuid()!=0?\"clean\":\"ROOT\")<<endl;}", "", CLEAN, {"Accepted"}),
}


def check(case, want, st, out, err, mem):
    if want == "MEM":  # program demonstrably started, then was stopped by the memory cap.
        # Judged by behaviour, not the reported figure: isolate v2's cg-mem is cgroup
        # memory.peak, which kernel 6.10 cannot reset between the compile and run steps,
        # so compiled languages report the compiler's peak (docs/JUDGE0_LANGUAGES.md).
        return st != "Accepted" and "started" in out and "ALLOCATED" not in out
    if want == "FITS":
        return st == "Accepted" and out.startswith("touched")
    return st in want and (case not in {"network", "secrets", "write_outside", "fork_bomb", "escalate"} or out == CLEAN)


TOUCH = {  # page-touching allocations the optimiser cannot remove
    "python": "import sys\nb=bytearray(%d*1024*1024)\nprint('touched')",
    "javascript": "const b=Buffer.alloc(%d*1024*1024,1);console.log('touched')",
    "cpp": CPP_H + "int main(){size_t n=(size_t)%d<<20;volatile char*p=(volatile char*)malloc(n);long s=0;for(size_t i=0;i<n;i+=4096)p[i]=1;for(size_t i=0;i<n;i+=4096)s+=p[i];cout<<\"touched \"<<s<<endl;}",
}
for _lang, _cases in (("python", P), ("javascript", JS), ("cpp", CPP)):
    _cases["mem_90MB_fits"] = (TOUCH[_lang] % 90, "", None, "FITS")
    _start = {"python": "import sys\nprint('started');sys.stdout.flush()\n",
              "javascript": "console.log('started');\n", "cpp": ""}[_lang]
    _big = TOUCH[_lang] % 180
    if _lang == "cpp":
        _big = _big.replace("int main(){", "int main(){cout<<\"started\"<<endl;", 1)
    _cases["mem_180MB_killed"] = (_start + _big, "", None, "MEM")


def main() -> int:
    ids = resolve_ids()
    p = f = 0
    for lang, cases in (("python", P), ("javascript", JS), ("cpp", CPP)):
        for case, (src, stdin, exp, want) in cases.items():
            st, out, err, mem, t = submit(ids[lang], src, stdin, exp)
            ok = check(case, want, st, out, err, mem)
            p += ok; f += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {lang:10} {case:13} status={st:26} mem={mem}KB time={t}s out={out[:40]!r}"
                  + ("" if ok else f" err={err[:160]!r}"))
    # cross-language concurrency, worker count 1: they must queue and all finish
    jobs = [("python", P["correct"]), ("javascript", JS["correct"]), ("cpp", CPP["correct"])]
    for label, batch in (("3 simultaneous (py/js/cpp)", jobs), ("6 queued (2 of each)", jobs * 2)):
        t0 = time.time()
        with cf.ThreadPoolExecutor(len(batch)) as ex:
            res = list(ex.map(lambda j: submit(ids[j[0]], j[1][0], j[1][1], j[1][2], timeout=240), batch))
        ok = all(r[0] == "Accepted" for r in res)
        p += ok; f += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {[r[0] for r in res]} in {time.time() - t0:.1f}s")
    print(f"RESULT: {p} passed, {f} failed")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
