"""Genera pisos/data/ref/{secciones_2024.json,renta_secciones.csv} desde el INE (se ejecuta a mano, no a diario).
- Límites: geoserver del INE (OGC API Features), secciones 2024 de los municipios de pisos.yml (cumun).
- Renta: Atlas de Distribución de Renta de los Hogares (INE, tabla 30896 = provincia de Barcelona), renta neta media por persona."""
import csv, json, subprocess, sys, urllib.parse
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "ref"
MUN = {"08019": "Barcelona", "08015": "Badalona", "08121": "Mataró", "08118": "El Masnou", "08172": "Premià de Mar"}
TABLA, GRUPO = 30896, 90783
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
    vals = curl(f"{INE}/wstempus/js/ES/VALORES_GRUPOSTABLA/{TABLA}/{GRUPO}", 90)
    name2cod = {v["Nombre"]: v["Codigo"] for v in vals}
    data = curl(f"{INE}/wstempus/js/ES/DATOS_TABLA/{TABLA}?nult=1", 300)
    rows = {}
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
    with open(OUT / "renta_secciones.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["codigo", "anyo", "renta_persona", "renta_hogar"])
        for c, r in sorted(rows.items()):
            w.writerow([c, r["anyo"], r.get("Renta neta media por persona"), r.get("Renta neta media por hogar")])
    print("unidades con renta:", len(rows))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    limites(); renta()
