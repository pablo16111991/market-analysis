"""Genera pisos/data/ref/municipios.csv: municipios a <= MAX_MIN minutos en coche del centro de Barcelona,
con su slug de Fotocasa comprobado. Se ejecuta a mano (no a diario); luego se copian los slugs a pisos.yml.

- Municipios y su punto central: secciones censales 2024 del INE (media de los centros de sus secciones, que
  pesa por población porque cada sección tiene una población parecida).
- Tiempo en coche: OSRM público (router.project-osrm.org), SIN tráfico, desde Plaça de Catalunya.
- Slug: nombre del INE pasado al formato de Fotocasa ("Vendrell, El" -> "el-vendrell"); se comprueba pidiendo
  la primera página de la búsqueda (si no existe, Fotocasa no devuelve resultados y se avisa).
Uso: python3 pisos/ref/build_zonas.py [--max-min 60]
"""
import argparse, csv, json, re, subprocess, sys, time, unicodedata, urllib.parse, urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "ref" / "municipios.csv"
ORIGIN = (2.1700, 41.3870)          # Plaça de Catalunya (lon, lat)
BBOX = "0.9,40.8,3.3,42.3"          # de sobra para 60-70 min desde Barcelona
INE = "https://www.ine.es/geoserver/ogc/features/v1/collections/WMS_INE_SECCIONES_G01:Secciones_2024/items"


def pretty(name):
    """'Vendrell, El' -> 'El Vendrell' (el INE pone el artículo al final)."""
    m = re.match(r"^(.*), (El|La|Els|Les|L')$", name)
    return (m.group(2) + ("" if m.group(2) == "L'" else " ") + m.group(1)) if m else name


def slug(name, cumun):
    if cumun == "08019":
        return "barcelona-capital"
    name = pretty(name)
    name = unicodedata.normalize("NFKD", name.split("/")[0]).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def municipios():
    q = urllib.parse.urlencode({"f": "json", "limit": 20000, "bbox": BBOX})
    d = json.loads(subprocess.run(["curl", "-s", "-m", "900", f"{INE}?{q}"], capture_output=True, check=True).stdout)
    if len(d["features"]) != d.get("numberMatched"):
        sys.exit(f"INE incompleto: {len(d['features'])} de {d.get('numberMatched')}")
    acc, names = defaultdict(list), {}
    for f in d["features"]:
        p, g = f["properties"], f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        pts = [pt for poly in polys for pt in poly[0]]
        acc[p["CUMUN"]].append((sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)))
        names[p["CUMUN"]] = (p["NMUN"], p["NPRO"])
    return {m: (sum(x for x, _ in v) / len(v), sum(y for _, y in v) / len(v), names[m]) for m, v in acc.items()}


def drive_times(mun):
    out, keys = {}, list(mun)
    for i in range(0, len(keys), 90):
        ks = keys[i:i + 90]
        coords = ";".join([f"{ORIGIN[0]},{ORIGIN[1]}"] + [f"{mun[k][0]:.5f},{mun[k][1]:.5f}" for k in ks])
        u = f"https://router.project-osrm.org/table/v1/driving/{coords}?sources=0&annotations=duration,distance"
        r = json.load(urllib.request.urlopen(u, timeout=120))
        for k, du, di in zip(ks, r["durations"][0][1:], r["distances"][0][1:]):
            out[k] = (du / 60 if du else None, di / 1000 if di else None)
        time.sleep(1)
    return out


def check_slug(client, collect, s):
    r = collect.fetch(client, collect.url(s, 1, {"min_price": 150000, "max_price": 350000, "min_rooms": 2}))
    return None if r is None else r.get("count")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-min", type=float, default=60)
    a = ap.parse_args()
    sys.path.insert(0, str(HERE.parent))
    import collect, httpx
    mun = municipios()
    t = drive_times(mun)
    sel = sorted((t[k][0], k) for k in mun if t[k][0] is not None and t[k][0] <= a.max_min)
    rows = []
    with httpx.Client(headers={"User-Agent": collect.UA, "Accept-Language": "es-ES"}, timeout=40,
                      follow_redirects=True) as c:
        for mins, k in sel:
            name, prov = mun[k][2]
            s = slug(name, k)
            n = check_slug(c, collect, s)
            if n is None:
                print(f"AVISO: slug sin resultados en Fotocasa: {name} -> {s}")
            rows.append({"cumun": k, "nombre": name, "ciudad": pretty(name), "provincia": prov, "slug": s, "min_bcn": round(mins, 1),
                         "km_bcn": round(t[k][1], 1), "lon": round(mun[k][0], 5), "lat": round(mun[k][1], 5),
                         "anuncios_test": n})
            time.sleep(1)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} municipios <= {a.max_min} min -> {OUT}")


if __name__ == "__main__":
    main()
