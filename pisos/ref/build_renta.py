"""Genera pisos/data/ref/{secciones_2024.json,renta_secciones.csv} desde el INE (se ejecuta a mano, no a diario).
- Límites: geoserver del INE (OGC API Features), secciones 2024 de los municipios de data/ref/municipios.csv
  (los de pisos.yml; se genera con ref/build_zonas.py).
- Renta: Atlas de Distribución de Renta de los Hogares (INE), renta neta media por persona. Una tabla por
  provincia: 30896 Barcelona, 31016 Girona, 31223 Tarragona."""
import csv, json, subprocess, sys, urllib.parse
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "ref"
MUN = {r["cumun"]: r["nombre"] for r in csv.DictReader(open(OUT / "municipios.csv", encoding="utf-8"))}
TABLAS = {"08": (30896, 90783), "17": (31016, 91299), "43": (31223, 92150)}   # provincia -> (tabla, grupo territorial)
INE = "https://servicios.ine.es"


def curl(url, timeout=180):
    return json.loads(subprocess.run(["curl", "-s", "-m", str(timeout), url], capture_output=True, check=True).stdout)


def rnd(c):
    return [[[round(x, 5), round(y, 5)] for x, y in ring] for ring in c]


def limites():
    """Una petición por municipio (la paginación del servidor del INE no es fiable con filtros múltiples)."""
    feats = []
    for m in MUN:
        q = urllib.parse.urlencode({"f": "json", "limit": 1500, "filter": f"CUMUN = '{m}' AND TIPO = 'SECCIONADO'", "filter-lang": "cql-text"})
        d = curl(f"https://www.ine.es/geoserver/ogc/features/v1/collections/WMS_INE_SECCIONES_G01:Secciones_2024/items?{q}", 300)
        if len(d["features"]) != d.get("numberMatched"):
            sys.exit(f"{m}: incompleto {len(d['features'])} de {d.get('numberMatched')}")
        for f in d["features"]:
            g = f["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            feats.append({"cusec": f["properties"]["CUSEC"], "mun": m, "polys": [rnd(p) for p in polys]})
    json.dump(feats, open(OUT / "secciones_2024.json", "w"), separators=(",", ":"))
    print("secciones:", len(feats))


def renta():
    rows = {}
    for prov in sorted({m[:2] for m in MUN}):
        tabla, grupo = TABLAS[prov]
        renta_tabla(tabla, grupo, rows)
    with open(OUT / "renta_secciones.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["codigo", "anyo", "renta_persona", "renta_hogar"])
        for c, r in sorted(rows.items()):
            w.writerow([c, r["anyo"], r.get("Renta neta media por persona"), r.get("Renta neta media por hogar")])
    print("unidades con renta:", len(rows))


def renta_tabla(tabla, grupo, rows):
    vals = curl(f"{INE}/wstempus/js/ES/VALORES_GRUPOSTABLA/{tabla}/{grupo}", 90)
    name2cod = {v["Nombre"]: v["Codigo"] for v in vals}
    data = curl(f"{INE}/wstempus/js/ES/DATOS_TABLA/{tabla}?nult=1", 300)
    for s in data:
        n = s["Nombre"]
        if "Dato base" not in n or not s["Data"]:
            continue
        parts = n.split(". Dato base. ")
        if len(parts) < 2:
            continue
        unit, ind = parts[0].strip(), parts[1].strip(" .")
        cod = name2cod.get(unit)
        if cod and ind in ("Renta neta media por persona", "Renta neta media por hogar"):
            rows.setdefault(cod, {"anyo": s["Data"][0]["Anyo"]})[ind] = s["Data"][0]["Valor"]


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    limites(); renta()
