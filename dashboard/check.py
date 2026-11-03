"""Comprobaciones de datos del dashboard (sin red). Uso: python3 dashboard/check.py [site/data.json]

Devuelve codigo 1 si hay problemas graves. Imprime un resumen util para vigilar la salud:
frescura, NaN, tamaño del conjunto, huecos de historico, columnas vacias, calidad del modelo.
"""
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dashboard", "site", "data.json")
raw = open(path, encoding="utf-8").read()
problems, notes = [], []

if "NaN" in raw or "Infinity" in raw:
    problems.append("data.json contiene NaN/Infinity (el navegador no lo puede leer)")
d = json.loads(raw.replace("NaN", "null").replace("-Infinity", "null").replace("Infinity", "null"))

gen = datetime.strptime(d["generated"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
age_h = (datetime.now(timezone.utc) - gen).total_seconds() / 3600
if age_h > 36:
    problems.append(f"datos con {age_h:.0f} h de antigüedad (se esperaba <36 h)")

p = d["pisos"]
rows = p["rows"]
act = [r for r in rows if r["a"]]
notes.append(f"pisos: {len(act)} activos, {len(rows)} en ambito, {p['retirados']} retirados acumulados")
if len(act) < 500:
    problems.append(f"muy pocos pisos activos ({len(act)})")
for col in ["price", "m2", "eur_m2", "barrio", "lat", "fair", "disc"]:
    miss = sum(1 for r in act if r.get(col) is None)
    notes.append(f"  vacios en '{col}': {miss}/{len(act)}")
    if col in ("price", "m2", "eur_m2") and miss > 0.02 * len(act):
        problems.append(f"columna '{col}' con {miss} vacios")
days = sorted(p["hist"])
notes.append(f"  historico: {len(days)} dias ({days[0]} .. {days[-1]})")
m = p["model"]
notes.append(f"  modelo: error mediano {m['med_pct']*100:.1f}%, sigma {m['sigma']:.3f}, n={m['n']}")
if m["med_pct"] > 0.15:
    problems.append(f"el modelo de precios empeora: error mediano {m['med_pct']*100:.1f}% (era ~9%)")
chollos = sum(1 for r in act if r.get("disc") is not None and r["disc"] <= -10 and not r["warn"])
notes.append(f"  chollos (>=10% bajo parecidos, sin avisos): {chollos}")

for name, prod in d["sh"].items():
    rs = prod["rows"]
    a = [r for r in rs if r["state"] == "activo" and r["sc"]]
    notes.append(f"second-hand {name}: {len(a)} activos en ambito, {sum(r['paid'] for r in rs)} vendidos/borrados")
    if not rs:
        problems.append(f"{name} sin filas")

print("\n".join(notes))
if problems:
    print("\nPROBLEMAS:\n- " + "\n- ".join(problems))
    sys.exit(1)
print("\nTODO OK")
