"""
Revisión humana de las etiquetas propuestas por Gemini (paso 2 del etiquetado).

Abre una página local con cada foto y sus etiquetas (tamaño, grupo de manto,
estado del pelo) en menús desplegables. Se corrige lo que esté mal y se marca
como revisada; todo se guarda en el mismo CSV al instante.

    python -m entrenamiento.clasificador_imagen.revisar --etiquetas READ/etiquetas_propuestas.csv
    -> abrir http://localhost:8790

Atajos: J / K = siguiente / anterior foto, R = marcar revisada y avanzar.
Solo escucha en localhost: las fotos no salen del computador.
"""

from __future__ import annotations

import argparse
import csv
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

RAIZ = Path(__file__).resolve().parents[2]
CAMPOS_EDITABLES = ("tamano", "grupo", "estado", "es_perro", "revisado", "nota_revision")

PAGINA = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Revisión de etiquetas</title>
<style>
:root{color-scheme:light;--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;--ok:#0ca30c;--warn:#fab219;--acc:#2a78d6}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#0d0d0d;--card:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--line:#2c2c2a;--acc:#3987e5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0}.prog{flex:1;min-width:160px;height:8px;background:var(--line);border-radius:4px;overflow:hidden}.prog i{display:block;height:100%;background:var(--ok)}
select,button,input{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:6px;padding:4px 6px}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;padding:16px}
.c{background:var(--card);border:2px solid var(--line);border-radius:10px;overflow:hidden}.c.act{border-color:var(--acc)}.c.rev{border-color:var(--ok)}
.c .b>span{min-width:0;display:flex;gap:6px;align-items:center}.c select,.c input[data-k=nota_revision]{max-width:100%;min-width:0;flex:1}
.c img{width:100%;height:260px;object-fit:contain;background:#000;cursor:zoom-in}.c .b{padding:8px 10px;display:grid;grid-template-columns:auto 1fr;gap:4px 8px;align-items:center}
.c .t{grid-column:1/-1;display:flex;justify-content:space-between;color:var(--ink2);font-size:12px}.conf{font-size:11px;color:var(--muted)}.baja{color:#d03b3b;font-weight:600}
label.r{grid-column:1/-1;display:flex;gap:6px;align-items:center;font-weight:600}.obs{grid-column:1/-1;font-size:11px;color:var(--muted)}
.ayuda{font-size:12px;color:var(--ink2)}dialog img{max-width:90vw;max-height:85vh}
</style></head><body>
<header><h1>🐾 Revisión de etiquetas</h1><div class="prog"><i id="barra"></i></div><span id="cuenta"></span>
<label>Mostrar <select id="filtro"><option value="pend">pendientes</option><option value="todas">todas</option><option value="dudosas">dudosas (&lt;0.75)</option></select></label>
<span class="ayuda">J/K moverse · R = revisada y siguiente · clic en la foto para ampliar</span></header>
<main id="m"></main><dialog id="z" onclick="this.close()"><img id="zi"></dialog>
<script>
const G={A_maquina:"A · máquina (shih tzu, schnauzer, poodle)",B_deslanado:"B · doble capa (husky, pug, labrador)",C_cepillado:"C · cepillado (golden)",D_corto:"D · pelo corto"};
const T={pequeno:"pequeño (≤9 kg)",mediano:"mediano (9–18 kg)",grande:"grande (18–45 kg)"};
const E={"":"— (no aplica / no se ve)",sin_motas:"sin nudos",moderado:"algunos nudos",severo:"muy enredado"};
let filas=[],act=0;
const opts=(o,v)=>Object.entries(o).map(([k,t])=>`<option value="${k}"${k===(v||"")?" selected":""}>${t}</option>`).join("");
const conf=v=>v===""||v==null?"":`<span class="conf ${+v<0.75?"baja":""}">${(+v).toFixed(2)}</span>`;
function visibles(){const f=document.getElementById("filtro").value;return filas.map((r,i)=>[r,i]).filter(([r])=>f==="todas"||(f==="pend"&&r.revisado!=="si")||(f==="dudosas"&&Math.min(+r.conf_tamano||1,+r.conf_grupo||1)<0.75));}
function pintar(){
  const v=visibles();document.getElementById("m").innerHTML=v.map(([r,i])=>`<div class="c ${r.revisado==="si"?"rev":""}" data-i="${i}">
  <img loading="lazy" src="/img/${encodeURIComponent(r.ruta)}" alt="${r.id_imagen}">
  <div class="b"><div class="t"><span>${r.id_imagen} · ${r.momento}${r.nombre_leido?" · "+r.nombre_leido:""}</span><span>${r.id_mascota_prov}</span></div>
  <span>Tamaño</span><span><select data-k="tamano">${opts(T,r.tamano)}</select> ${conf(r.conf_tamano)}</span>
  <span>Pelo</span><span><select data-k="grupo">${opts(G,r.grupo)}</select> ${conf(r.conf_grupo)}</span>
  <span>Estado</span><span><select data-k="estado">${opts(E,r.estado)}</select> ${conf(r.conf_estado)}</span>
  <span>¿Perro?</span><span><select data-k="es_perro">${opts({si:"sí, uno solo",no:"no / varios / no sirve"},r.es_perro)}</select></span>
  <span>Nota</span><span><input data-k="nota_revision" value="${(r.nota_revision||"").replace(/"/g,"&quot;")}" style="width:100%"></span>
  ${r.observacion?`<div class="obs">Gemini: ${r.observacion}</div>`:""}
  <label class="r"><input type="checkbox" data-k="revisado" ${r.revisado==="si"?"checked":""}> Revisada</label></div></div>`).join("")||"<p style='padding:20px'>Nada pendiente 🎉</p>";
  document.querySelectorAll(".c").forEach(c=>{const i=+c.dataset.i;
    c.querySelectorAll("[data-k]").forEach(el=>el.addEventListener("change",()=>guardar(i,el.dataset.k,el.type==="checkbox"?(el.checked?"si":""):el.value)));
    c.querySelector("img").onclick=()=>{zi.src=c.querySelector("img").src;z.showModal();};c.onmouseenter=()=>marcar(i);});
  progreso();
}
function progreso(){const n=filas.filter(r=>r.revisado==="si").length;document.getElementById("barra").style.width=(100*n/filas.length)+"%";document.getElementById("cuenta").textContent=`${n} / ${filas.length} revisadas`;}
async function guardar(i,k,v){filas[i][k]=v;await fetch("/guardar",{method:"POST",body:JSON.stringify({id:filas[i].id_imagen,campo:k,valor:v})});
  const c=document.querySelector(`.c[data-i="${i}"]`);if(c)c.classList.toggle("rev",filas[i].revisado==="si");progreso();}
function marcar(i){act=i;document.querySelectorAll(".c").forEach(c=>c.classList.toggle("act",+c.dataset.i===i));}
function mover(d){const v=visibles().map(([,i])=>i);let p=v.indexOf(act)+d;if(p<0)p=0;if(p>=v.length)p=v.length-1;if(v[p]==null)return;marcar(v[p]);document.querySelector(`.c[data-i="${v[p]}"]`).scrollIntoView({block:"center",behavior:"smooth"});}
addEventListener("keydown",e=>{if(["INPUT","SELECT"].includes(e.target.tagName))return;
  if(e.key==="j")mover(1);if(e.key==="k")mover(-1);
  if(e.key==="r"){guardar(act,"revisado","si").then(()=>{const cb=document.querySelector(`.c[data-i="${act}"] [data-k=revisado]`);if(cb)cb.checked=true;mover(1);});}});
document.getElementById("filtro").onchange=pintar;
fetch("/datos").then(r=>r.json()).then(d=>{filas=d;pintar();const v=visibles();if(v.length)marcar(v[0][1]);});
</script></body></html>"""


class Revision:
    def __init__(self, ruta_csv: Path, raiz_imagenes: list[Path]):
        self.ruta = ruta_csv
        self.raices = raiz_imagenes
        self.lock = threading.Lock()
        with open(ruta_csv, encoding="utf-8-sig") as fh:
            lector = csv.DictReader(fh)
            self.columnas = list(lector.fieldnames)
            self.filas = list(lector)
        if "nota_revision" not in self.columnas:
            self.columnas.append("nota_revision")

    def guardar(self, id_imagen: str, campo: str, valor: str) -> None:
        if campo not in CAMPOS_EDITABLES:
            raise ValueError(campo)
        with self.lock:
            for f in self.filas:
                if f["id_imagen"] == id_imagen:
                    f[campo] = valor
            tmp = self.ruta.with_suffix(".tmp")
            with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=self.columnas)
                w.writeheader()
                w.writerows(self.filas)
            tmp.replace(self.ruta)

    def imagen(self, ruta_rel: str) -> Path | None:
        nombre = Path(ruta_rel).name  # solo el nombre: evita salir de las carpetas permitidas
        for raiz in self.raices:
            p = raiz / nombre
            if p.is_file():
                return p
        return None


def servidor(rev: Revision, puerto: int) -> ThreadingHTTPServer:
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _enviar(self, codigo, cuerpo: bytes, tipo: str):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self):
            ruta = urlparse(self.path).path
            if ruta == "/":
                self._enviar(200, PAGINA.encode("utf-8"), "text/html; charset=utf-8")
            elif ruta == "/datos":
                self._enviar(200, json.dumps(rev.filas, ensure_ascii=False).encode("utf-8"), "application/json")
            elif ruta.startswith("/img/"):
                p = rev.imagen(unquote(ruta[5:]))
                if p:
                    self._enviar(200, p.read_bytes(), "image/jpeg")
                else:
                    self._enviar(404, b"", "text/plain")
            else:
                self._enviar(404, b"", "text/plain")

        def do_POST(self):
            if urlparse(self.path).path != "/guardar":
                return self._enviar(404, b"", "text/plain")
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                rev.guardar(d["id"], d["campo"], d["valor"])
                self._enviar(200, b"{}", "application/json")
            except ValueError:
                self._enviar(400, b"", "text/plain")

    return ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etiquetas", type=Path, default=RAIZ / "READ" / "etiquetas_propuestas.csv")
    ap.add_argument("--imagenes", type=Path, action="append", default=None,
                    help="carpetas con las fotos (por defecto, las dos partes del dataset en READ/)")
    ap.add_argument("--puerto", type=int, default=8790)
    args = ap.parse_args()
    raices = args.imagenes or [
        RAIZ / "READ" / "Dataset_FB_v1_SCRUM101_parte1" / "dataset_fb_v1" / "imagenes",
        RAIZ / "READ" / "Dataset_FB_v1_SCRUM101_parte2" / "dataset_fb_v1" / "imagenes",
    ]
    rev = Revision(args.etiquetas, raices)
    srv = servidor(rev, args.puerto)
    url = f"http://localhost:{args.puerto}"
    print(f"Revisión abierta en {url}  ({len(rev.filas)} fotos). Ctrl+C para terminar; todo queda guardado.")
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
