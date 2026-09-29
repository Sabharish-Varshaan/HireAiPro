#!/bin/bash
# Attack battery against isolate v2.6 --cg with Judge0-equivalent limits.
PASS=0; FAIL=0
export POSTGRES_PASSWORD=CANARY_7f3a JUDGE0_SECRET_CANARY=CANARY_7f3a; mkdir -p /api && echo "db_password=CANARY_7f3a" > /api/.env
run() { # name expect(status regex) program [extra isolate args]
  local name=$1 expect=$2 prog=$3; shift 3
  isolate --cg -b 1 --cleanup >/dev/null 2>&1; isolate --cg -b 1 --init >/dev/null
  printf '%s\n' "$prog" > /var/local/lib/isolate/1/box/t.py
  isolate --cg -b 1 -t 2 -x 0.5 -w 5 -k 64000 -p60 -n 512 --cg-mem=128000 -f 1024 -E HOME=/tmp \
      -M /tmp/meta "$@" --run -- "${PY:-/usr/bin/python3}" t.py >/tmp/out 2>/tmp/err
  local st=$(grep -E '^status:' /tmp/meta | cut -d: -f2); local out=$(head -c 200 /tmp/out | tr '\n' ' ')
  local line="status=${st:-OK} exit=$(grep exitcode /tmp/meta|cut -d: -f2) mem=$(grep cg-mem /tmp/meta|cut -d: -f2)KB oom=$(grep -c cg-oom-killed /tmp/meta) out=[$out]"
  if [[ "${st:-OK} $out" =~ $expect ]]; then PASS=$((PASS+1)); echo "PASS  $name :: $line"; else FAIL=$((FAIL+1)); echo "FAIL  $name :: $line :: expected /$expect/ :: err=$(head -c 200 /tmp/err)"; fi
}
run "hello world"            '^OK hello'           'print("hello")'
run "cpu infinite loop"      '^TO'                 'while True: pass'
run "wall-clock sleep"       '^TO'                 'import time; time.sleep(60)'
run "memory bomb 1GB"        '^(SG|RE) started ?$'   'import sys; print("started"); sys.stdout.flush(); x = bytearray(1024*1024*1024); print("ALLOCATED")'
run "fork bomb"              'forks_capped'        'import os
n=0
try:
    while n<1000: 
        if os.fork()==0:
            import time; time.sleep(3); os._exit(0)
        n+=1
except OSError: pass
print("forks_capped" if n<1000 else "UNLIMITED", n)'
run "network egress"         'blocked'             'import socket
try:
    socket.create_connection(("1.1.1.1",53),timeout=2); print("CONNECTED")
except OSError as e: print("blocked", e.errno)'
run "read /etc/shadow"       'denied'              'try: print(open("/etc/shadow").read()[:20])
except OSError as e: print("denied", e.errno)'
run "container-only paths"   'denied'              'import os
hits=[p for p in ("/entry.sh","/etc/subuid","/etc/sudoers.d","/root","/api","/run/isolate/locks") if os.path.exists(p)]
print("denied" if not hits else "VISIBLE "+" ".join(hits))'
run "secret env not inherited" 'clean'             'import os
leak=[k for k in os.environ if any(w in k.upper() for w in ("PASS","SECRET","TOKEN","KEY","POSTGRES","REDIS"))]
print("clean" if not leak else "LEAK "+str(leak))'
run "/usr is read-only"       'readonly'           'try: open("/usr/local/etc/isolate","a"); print("WRITABLE")
except OSError as e: print("readonly", e.errno)'
run "secret grep over visible fs" 'nosecret'       'import os
found=[]
for root in ("/usr/local/etc","/usr/local/bin","/tmp","/box","/etc","/var"):
    for dp,_,fs in os.walk(root):
        for f in fs:
            try:
                if os.path.join(dp,f) != "/box/t.py" and (b"CANARY" + b"_7f3a") in open(os.path.join(dp,f),"rb").read(2_000_000): found.append(os.path.join(dp,f))
            except OSError: pass
print("nosecret" if not found else "FOUND "+str(found))'
run "write outside box"      'denied'              'ok=[]
for p in ("/usr/pwn","/bin/pwn","/var/local/lib/isolate/pwn","/pwn"):
    try: open(p,"w").write("x"); ok.append(p)
    except OSError: pass
print("denied" if not ok else "WROTE "+" ".join(ok))'
run "runs as non-root"       'nonroot'             'import os; print("nonroot" if os.getuid()!=0 and os.geteuid()!=0 else "ROOT", os.getuid())'
run "setuid to root"         'denied'              'import os
try: os.setuid(0); print("BECAME_ROOT")
except OSError as e: print("denied", e.errno)'
run "see host processes"     'isolated'            'import os
pids=[p for p in os.listdir("/proc") if p.isdigit()]
print("isolated" if len(pids)<=3 else "SEES "+str(len(pids)), pids)'
run "output size limit"      'limited 27' 'try:
    open("big","w").write("x"*10*1024*1024); print("WROTE_10MB")
except OSError as e: print("limited", e.errno)'
run "ptrace (seccomp/caps)"  'denied'              'import ctypes
libc=ctypes.CDLL(None); r=libc.ptrace(16,1,0,0)
print("denied" if r!=0 else "ATTACHED_PID1")'
run "mount syscall"          'denied'              'import ctypes
libc=ctypes.CDLL(None,use_errno=True); r=libc.mount(b"none",b"/tmp",b"tmpfs",0,None)
print("denied" if r!=0 else "MOUNTED")'
# cross-box isolation: secret in box 2 must be invisible from box 1
isolate --cg -b 2 --cleanup >/dev/null 2>&1; isolate --cg -b 2 --init >/dev/null; echo TOPSECRET > /var/local/lib/isolate/2/box/secret
run "read other box"         'denied'              'import glob; f=glob.glob("/var/local/lib/isolate/*/box/secret")+glob.glob("/box/../*/box/secret")
print("denied" if not f else "LEAK "+str(f))'
# no leftover processes after all boxes
isolate --cg -b 1 --cleanup >/dev/null 2>&1; isolate --cg -b 2 --cleanup >/dev/null 2>&1; sleep 1
left=0; for d in /proc/[0-9]*; do u=$(awk '/^Uid:/{print $2}' $d/status 2>/dev/null); [ -n "$u" ] && [ "$u" -ge 60000 ] && [ "$u" -lt 61000 ] && left=$((left+1)); done
if [ "$left" -eq 0 ]; then PASS=$((PASS+1)); echo "PASS  no leftover sandbox processes"; else FAIL=$((FAIL+1)); echo "FAIL  $left leftover sandbox processes"; fi
echo "RESULT: $PASS passed, $FAIL failed"
