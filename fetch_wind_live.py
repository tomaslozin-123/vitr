#!/usr/bin/env python3
"""Přehled větru z meteostanic ČHMÚ: místní stránka s tlačítkem Aktualizovat.

    python fetch_wind_live.py          # spustí server a otevře stránku v prohlížeči
    python fetch_wind_live.py --lan    # stránka půjde otevřít i z telefonu ve stejné Wi-Fi

Okno s tímto programem nechte otevřené, zavřením se zastaví. Stanice jsou v config.json.
"""
import argparse
import json
import socket
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

API = "https://data-provider.chmi.cz/api/graphs/graf.meteo-stanice.vitr-10m"


def get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "wind-overview/0.3", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def num(v):
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def load_station(st, hours):
    """Řádky [čas_ms_utc, rychlost_ms, náraz_ms] za posledních `hours` hodin."""
    data = get(f"{API}/{st['id']}")
    limit = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    for p in data.get("dataPoints", []):
        t = datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
        v = p.get("values") or {}
        if t >= limit:
            rows.append([int(t.timestamp() * 1000), num(v.get("F")), num(v.get("Fmax"))])
    return sorted(rows)


def read_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    sts = []
    for s in cfg["stations"]:
        if isinstance(s, str):
            s = {"id": s.upper(), "name": s.upper()}
        sts.append({"id": s["id"].upper(), "name": s.get("name", s["id"])})
    return {"hours": int(cfg.get("hours", 3)), "stations": sts}


def collect(cfg):
    def one(st):
        try:
            return {"name": st["name"], "rows": load_station(st, cfg["hours"])}
        except Exception as e:  # jedna stanice nesmí shodit ostatní
            return {"name": st["name"], "rows": [], "error": str(e)}
    with ThreadPoolExecutor(max_workers=max(1, len(cfg["stations"]))) as ex:
        res = list(ex.map(one, cfg["stations"]))
    return {"hours": cfg["hours"], "stations": res}


PAGE = """<!doctype html><html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Vítr – ČHMÚ</title>
<style>
:root{--bg:#f3f5f7;--sf:#fff;--ink:#14202b;--mu:#5b6b7a;--ln:#d9e0e6;--sp:#1f6fb2;--gu:#c2410c;--g2:#a16207;--g3:#c2410c;--g4:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#0e1620;--sf:#16212d;--ink:#e6edf3;--mu:#93a4b5;--ln:#27384a;--sp:#6db3f2;--gu:#fb923c;--g2:#eab308;--g3:#fb923c;--g4:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:14px 12px 40px}h1{font-size:1.3rem;margin:0 0 10px}
.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
button,select{font:inherit;color:inherit;background:var(--sf);border:1px solid var(--ln);border-radius:8px;padding:8px 12px;cursor:pointer}
button{font-weight:600}button:disabled{opacity:.6;cursor:wait}:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
#st{color:var(--mu);font-size:.88rem}.err{color:var(--g4);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}
.card{background:var(--sf);border:1px solid var(--ln);border-radius:8px;padding:10px 12px}
.card h2{font-size:1rem;margin:0}.cur{display:flex;gap:16px;margin:4px 0 2px;font-variant-numeric:tabular-nums}
.cur b{font-size:1.5rem}.cur small,.when{color:var(--mu);font-size:.8rem}
svg{width:100%;height:auto;display:block}svg text{fill:var(--mu);font-size:10px}
.leg{color:var(--mu);font-size:.82rem;margin:8px 0}
.wrap{overflow-x:auto;margin-top:12px;background:var(--sf);border:1px solid var(--ln);border-radius:8px}
table{width:100%;border-collapse:collapse}th,td{padding:6px 10px;border-bottom:1px solid var(--ln);text-align:right;font-variant-numeric:tabular-nums}
th{font-weight:600;font-size:.84rem;color:var(--mu)}th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:0}.s{border-left:1px solid var(--ln)}
.g2{color:var(--g2);font-weight:600}.g3{color:var(--g3);font-weight:700}.g4{color:var(--g4);font-weight:800}
</style></head><body><main>
<h1>Vítr na meteostanicích ČHMÚ</h1>
<div class="bar"><button id="go">Aktualizovat</button>
<select id="unit" aria-label="Jednotky"><option value="ms">m/s</option><option value="kmh">km/h</option></select>
<span id="st"></span></div>
<div id="out"></div>
<p class="leg">Plná čára je průměrná rychlost za 10 minut, čárkovaná je maximální náraz v intervalu. Všechny grafy mají stejnou osu, takže je lze přímo porovnat. Barva nárazu v tabulce: nad 40, 60 a 90 km/h. Zdroj: ČHMÚ, údaje jsou předběžné.</p>
</main><script>
const $=id=>document.getElementById(id);let DATA=null,unit="ms";
const conv=v=>v==null?null:unit==="ms"?v:v*3.6;
const fmt=v=>{v=conv(v);return v==null?"–":(unit==="ms"?v.toFixed(1):String(Math.round(v))).replace(".",",")};
const hm=t=>new Date(t).toLocaleTimeString("cs-CZ",{hour:"2-digit",minute:"2-digit",timeZone:"Europe/Prague"});
const gc=v=>v==null?"":v*3.6>=90?"g4":v*3.6>=60?"g3":v*3.6>=40?"g2":"";
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function chart(rows,top,step,t0,t1){
 const W=320,H=150,L=30,R=8,T=8,B=20,x=t=>L+(t-t0)/(t1-t0)*(W-L-R),y=v=>T+(1-conv(v)/top)*(H-T-B);
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Graf rychlosti a nárazů větru">`;
 for(let v=0;v<=top+1e-9;v+=step){const yy=T+(1-v/top)*(H-T-B);
  s+=`<line x1="${L}" x2="${W-R}" y1="${yy}" y2="${yy}" stroke="var(--ln)"/><text x="${L-4}" y="${yy+3}" text-anchor="end">${String(v).replace(".",",")}</text>`}
 for(let h=Math.ceil(t0/36e5)*36e5;h<=t1;h+=36e5)s+=`<text x="${x(h)}" y="${H-5}" text-anchor="middle">${hm(h)}</text>`;
 const line=(i,col,dash,w)=>{const p=rows.filter(r=>r[i]!=null).map(r=>`${x(r[0]).toFixed(1)},${y(r[i]).toFixed(1)}`).join(" ");
  return p?`<polyline points="${p}" fill="none" stroke="${col}" stroke-width="${w}" ${dash?'stroke-dasharray="4 3"':""} stroke-linejoin="round"/>`:""};
 return s+line(2,"var(--gu)",true,1.5)+line(1,"var(--sp)",false,2)+"</svg>"}
function render(){
 const sts=DATA.stations,all=sts.flatMap(s=>s.rows);
 if(!all.length){$("out").innerHTML='<p class="err">Žádná data. Zkontrolujte kódy stanic v config.json.</p>'+sts.filter(s=>s.error).map(s=>`<p class="err">${esc(s.name)}: ${esc(s.error)}</p>`).join("");return}
 const t1=Math.max(...all.map(r=>r[0])),t0=t1-DATA.hours*36e5;
 const mx=conv(Math.max(...all.map(r=>Math.max(r[1]??0,r[2]??0))));
 const step=mx<=8?2:mx<=20?5:mx<=60?10:20,top=Math.max(step,Math.ceil(mx/step)*step);
 let h='<div class="grid">';
 for(const s of sts){const last=s.rows[s.rows.length-1];
  h+=`<div class="card"><h2>${esc(s.name)}</h2>`;
  if(s.error)h+=`<p class="err">${esc(s.error)}</p>`;
  else if(last)h+=`<div class="cur"><span><b>${fmt(last[1])}</b> <small>rychlost</small></span><span><b class="${gc(last[2])}">${fmt(last[2])}</b> <small>náraz ${unit==="ms"?"m/s":"km/h"}</small></span></div><div class="when">interval do ${hm(last[0])}</div>`+chart(s.rows,top,step,t0,t1);
  else h+="<p>Žádná data.</p>";
  h+="</div>"}
 h+="</div>";
 const times=[...new Set(all.map(r=>r[0]))].sort((a,b)=>b-a),maps=sts.map(s=>new Map(s.rows.map(r=>[r[0],r])));
 h+=`<div class="wrap"><table><tr><th rowspan="2">Čas</th>${sts.map(s=>`<th colspan="2" class="s">${esc(s.name)}</th>`).join("")}</tr>`;
 h+=`<tr>${sts.map(()=>`<th class="s">rychlost</th><th>náraz</th>`).join("")}</tr>`;
 for(const t of times)h+=`<tr><td>${hm(t)}</td>${maps.map(m=>{const r=m.get(t);return r?`<td class="s">${fmt(r[1])}</td><td class="${gc(r[2])}">${fmt(r[2])}</td>`:`<td class="s">–</td><td>–</td>`}).join("")}</tr>`;
 $("out").innerHTML=h+"</table></div>"}
async function refresh(){
 $("go").disabled=true;$("st").textContent="Načítám…";
 try{const r=await fetch("/api/data");if(!r.ok)throw new Error("HTTP "+r.status);DATA=await r.json();render();
  $("st").textContent="Aktualizováno "+new Date().toLocaleTimeString("cs-CZ")+", jednotky: "+(unit==="ms"?"m/s":"km/h")}
 catch(e){$("st").innerHTML='<span class="err">Nepodařilo se načíst: '+esc(e.message)+"</span>"}
 $("go").disabled=false}
$("go").addEventListener("click",refresh);
$("unit").addEventListener("change",e=>{unit=e.target.value;if(DATA)render()});
refresh();setInterval(refresh,600000);
</script></body></html>"""


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "IP-počítače"
    finally:
        s.close()


def make_handler(config_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/data"):
                try:
                    body = json.dumps(collect(read_config(config_path))).encode("utf-8")
                except Exception as e:
                    self.send_error(500, f"config.json: {e}")
                    return
                ctype = "application/json; charset=utf-8"
            elif self.path in ("/", "/index.html"):
                body, ctype = PAGE.encode("utf-8"), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.json")))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--lan", action="store_true", help="zpřístupnit i ostatním zařízením v síti")
    args = ap.parse_args()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.port), make_handler(args.config))
    print(f"Stránka běží na http://127.0.0.1:{args.port}")
    if args.lan:
        print(f"Na telefonu ve stejné Wi-Fi otevřete http://{lan_ip()}:{args.port}")
    print("Okno nechte otevřené. Ukončení: Ctrl+C.")
    webbrowser.open(f"http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nKonec.")


if __name__ == "__main__":
    main()
