#!/usr/bin/env python3
"""
progress_ui.py: a very small page that shows the progress and the estimated time left of a
run_pipeline.py run. It only reads Pipeline/logs/status.json (written by the runner).

    python Pipeline/progress_ui.py            # then open http://localhost:8765
"""
import http.server
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
STATUS = HERE / "logs" / "status.json"
PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Pipeline progress</title>
<style>
:root{--bg:#fff;--fg:#1c2320;--mut:#5d6b64;--line:#d9e0dc;--acc:#2f7d57;--bad:#b3392f}
@media(prefers-color-scheme:dark){:root{--bg:#141917;--fg:#e4ebe7;--mut:#9aa7a0;--line:#2f3a35;--acc:#7cc5a0;--bad:#e07a6f}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:640px;margin:0 auto;padding:24px 16px}
h1{font-size:20px;margin:0 0 4px}.mut{color:var(--mut);font-size:14px}
.bar{height:14px;background:var(--line);border-radius:7px;overflow:hidden;margin:16px 0 8px}
.bar i{display:block;height:100%;background:var(--acc);width:0;transition:width .4s}
.big{font-size:28px;font-weight:600}.row{display:flex;justify-content:space-between;gap:12px;margin:14px 0}
ul{list-style:none;padding:0;margin:16px 0}li{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line);font-size:14px}
.bad{color:var(--bad)}
</style><main>
<h1 id=t>Pipeline progress</h1><div class=mut id=sub>waiting for a run...</div>
<div class=bar><i id=b></i></div>
<div class=row><div><div class=mut>Steps</div><div class=big id=s>-</div></div>
<div><div class=mut>Elapsed</div><div class=big id=e>-</div></div>
<div><div class=mut>Time left (estimate)</div><div class=big id=r>-</div></div></div>
<div id=cur class=mut></div>
<div class=bar id=sb style="height:8px;display:none"><i id=sbi></i></div>
<pre id=ln class=mut style="white-space:pre-wrap;font-size:12px;margin:6px 0"></pre><ul id=l></ul></main>
<script>
const f=s=>{s=Math.max(0,Math.round(s));const m=Math.floor(s/60);return m>=60?Math.floor(m/60)+"h "+m%60+"m":m+"m "+String(s%60).padStart(2,"0")+"s"};
async function tick(){try{
 const d=await (await fetch("status.json?"+Date.now())).json();
 const now=d.finished?d.now:Date.now()/1000;
 b.style.width=(100*d.done/d.total)+"%";s.textContent=d.done+" / "+d.total;
 e.textContent=f(now-d.started);r.textContent=d.finished?"done":"~"+f(d.eta_seconds);
 sub.textContent=d.mode+" on "+d.db+(d.limit?", "+d.limit+" records for the API-bound steps":"");
 const c=d.current,pr=c&&c.progress;sb.style.display=pr?"block":"none";if(pr)sbi.style.width=(100*pr[0]/pr[1])+"%";
 ln.textContent=c&&c.line?c.line:"";
 cur.textContent=d.current?"Running step "+d.current.n+": "+d.current.name+" ("+f(now-d.current.since)+")"+(pr?"  "+pr[0]+" / "+pr[1]:""):(d.finished?"Finished.":"");
 l.innerHTML=d.steps.map(x=>`<li><span>${x.n} ${x.name}</span><span class="${x.status.startsWith("FAILED")||x.status=="TIMEOUT"?"bad":""}">${x.status} ${x.secs}s</span></li>`).join("");
}catch(_){}setTimeout(tick,2000)}tick();
</script>"""


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/status.json"):
            body, ctype = (STATUS.read_bytes() if STATUS.exists() else b"{}"), "application/json"
        else:
            body, ctype = PAGE.encode(), "text/html; charset=utf-8"
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("Progress page: http://localhost:8765  (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
