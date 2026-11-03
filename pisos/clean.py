"""Reconstruye data/clean/<search>.csv (1 fila por anuncio, último estado) desde TODO lo crudo."""
import csv, glob, json, re, sys
from collections import defaultdict
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent
COLS = ["id", "url", "state", "in_scope", "price_first", "price_last", "price_changes", "drop_pct", "reduced_price",
        "eur_m2", "rooms", "bathrooms", "surface", "floor", "subtype", "exterior", "antiquity", "conservation",
        "orientation", "energy", "energy_kwh", "co2", "construction", "ground_surface", "locality", "neighborhood", "municipality", "zone", "lat", "lon", "client_type", "client_alias",
        "occupied", "bare_ownership", "auctioned", "rented", "new_construction", "okupa_txt", "nuda_txt", "a_reformar", "seccion", "renta_idx_seccion", "renta_idx", "nivel_zona", "publication_date", "first_seen",
        "last_seen", "days_listed", "runs_seen", "dup_n", "dup_group", "desc_start"]


RE_OKUPA = re.compile(r"okup|ocupaci[oó]n ilegal|ocupantes ilegales|con los ocupantes|sin posesi[oó]n", re.I)
RE_OCUPADO = re.compile(r"ocupad[oa]s?\b", re.I)
RE_OKUPA_NEG = re.compile(r"(no|sin|libre de|desocupad)\W+(est[aá]\W+)?(ocupad|ocupantes|okup)|no (est[aá] )?okup", re.I)
RE_NUDA = re.compile(r"nuda\s+propiedad|nua\s+propiedad|usufructo|usufructuari", re.I)
RE_REFORMAR = re.compile(r"a reformar|para reformar|reforma integral|a rehabilitar|necesita (una )?reforma|para entrar a reformar", re.I)


def descriptions():
    d = {}
    p = ROOT / "data/raw/items.jsonl"
    if p.exists():
        for line in open(p, encoding="utf-8"):
            o = json.loads(line); d[str(o["id"])] = o["item"].get("description") or ""
    return d


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# --- Renta por zona (INE, ver ref/build_renta.py): índice 100 = media de Barcelona ciudad ---
REF = ROOT / "data" / "ref"
BANDS = [75, 90, 110, 135]  # cortes del índice -> niveles 1..5 (1 baja, 2 media-baja, 3 media, 4 media-alta, 5 alta)


def _inside(x, y, ring):
    c = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def load_renta():
    p, q = REF / "secciones_2024.json", REF / "renta_secciones.csv"
    if not (p.exists() and q.exists()):
        return None, {}, None
    renta = {r["codigo"]: num(r["renta_persona"]) for r in csv.DictReader(open(q, encoding="utf-8"))}
    base = renta.get("08019")  # Barcelona ciudad
    secs = []
    for s in json.load(open(p)):
        for poly in s["polys"]:
            xs = [pt[0] for pt in poly[0]]; ys = [pt[1] for pt in poly[0]]
            secs.append((min(xs), max(xs), min(ys), max(ys), poly, s["cusec"]))
    return secs, renta, base


def seccion(secs, lon, lat):
    for x0, x1, y0, y1, poly, cusec in secs:
        if x0 <= lon <= x1 and y0 <= lat <= y1 and _inside(lon, lat, poly[0]) and not any(_inside(lon, lat, h) for h in poly[1:]):
            return cusec
    return None


def nivel(idx):
    return None if idx is None else 1 + sum(idx >= b for b in BANDS)


def in_scope(r, sc):
    # Siempre fuera: ocupado/okupa, nuda propiedad/usufructo y subasta (por bandera de Fotocasa o por texto).
    # Los alquilados con inquilinos (rented) SÍ entran: se reportan con su columna.
    if r["occupied"] == "1" or r["bare_ownership"] == "1" or r["auctioned"] == "1" or r["okupa_txt"] or r["nuda_txt"]:
        return 0
    sc = sc or {}
    ex = {n.lower() for n in sc.get("exclude_neighborhoods", [])}
    if ex and ((r["neighborhood"] or "").lower() in ex or (r["locality"] + "/" + (r["neighborhood"] or "")).lower() in ex):
        return 0
    if sc.get("min_renta_idx") and (r.get("renta_idx") or 0) < sc["min_renta_idx"]:
        return 0
    if sc.get("min_nivel_zona") and (r.get("nivel_zona") or 0) < sc["min_nivel_zona"]:
        return 0
    if sc.get("min_surface") and not (num(r["surface"]) or 0) >= sc["min_surface"]:
        return 0
    if sc.get("subtypes") and r["subtype"] not in sc["subtypes"]:
        return 0
    if sc.get("exterior") and r["exterior"] != "1":
        return 0
    return 1


def build(sid, scope):
    files = sorted(glob.glob(str(ROOT / "data/raw/*_search*.csv")))
    rows = []
    for f in files:
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if r["search"] == sid:
                r["_complete"] = "INCOMPLETO" not in f
                rows.append(r)
    if not rows:
        return
    descs = descriptions()
    removed, now_price, extra = set(), {}, {}
    for f in sorted(glob.glob(str(ROOT / "data/raw/*_status.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if r["exists"] == "0":
                removed.add(r["id"])
            elif r["exists"] == "1":
                removed.discard(r["id"]); now_price[r["id"]] = num(r["price_now"])
    for f in sorted(glob.glob(str(ROOT / "data/raw/*_details.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            extra[r["id"]] = r
    runs = sorted({r["run_id"] for r in rows if r["_complete"]})
    last_run = runs[-1] if runs else None
    by = defaultdict(list)
    for r in rows:
        by[r["id"]].append(r)
    recs = []
    for iid, rs in by.items():
        rs.sort(key=lambda r: r["seen_at"])
        first, last = rs[0], rs[-1]
        prices = [num(r["price"]) for r in rs if num(r["price"])]
        changes = sum(1 for a, b in zip(prices, prices[1:]) if a != b)
        seen_last = any(r["run_id"] == last_run for r in rs)
        d = dict(last)
        for k in ("neighborhood", "municipality", "locality"):
            d[k] = (d.get(k) or "").strip()
        sur = num(d["surface"])
        d.update({
            "state": "activo" if seen_last else ("retirado" if iid in removed else ("fuera_de_filtro" if iid in now_price else "desaparecido")),
            "price_first": prices[0], "price_last": prices[-1], "price_changes": changes,
            "drop_pct": round(100 * (prices[-1] - prices[0]) / prices[0], 1) if prices[0] else None,
            "eur_m2": round(prices[-1] / sur) if sur else None,
            "first_seen": first["seen_at"][:10], "last_seen": last["seen_at"][:10], "runs_seen": len({r["seen_at"][:10] for r in rs}),
        })
        try:
            from datetime import date
            d["days_listed"] = (date.fromisoformat(last["seen_at"][:10]) - date.fromisoformat(d["publication_date"])).days
        except ValueError:
            d["days_listed"] = None
        if iid in now_price and now_price[iid] and not seen_last:
            d["price_last"] = now_price[iid]
            d["drop_pct"] = round(100 * (d["price_last"] - prices[0]) / prices[0], 1)
            d["eur_m2"] = round(d["price_last"] / sur) if sur else None
        e = extra.get(iid, {})
        d.update({k: e.get(k) for k in ("energy", "energy_kwh", "co2", "construction", "ground_surface")})
        txt = descs.get(iid, "")
        t = RE_OKUPA_NEG.sub(" ", txt)
        # "ocupado" suelto solo cuenta si no está alquilado con inquilinos (esos entran)
        d["okupa_txt"] = int(bool(RE_OKUPA.search(t)) or (d["rented"] != "1" and bool(RE_OCUPADO.search(t))))
        d["nuda_txt"] = int(bool(RE_NUDA.search(txt)))
        d["a_reformar"] = int(bool(RE_REFORMAR.search(txt)))
        recs.append(d)
    # Renta de la zona (INE). Por barrio = mediana de sus pisos, porque Fotocasa da coordenadas aproximadas.
    secs, renta, base = load_renta()
    for r in recs:
        r["seccion"] = r["renta_idx_seccion"] = None
        if secs and num(r["lat"]) and num(r["lon"]):
            cs = seccion(secs, num(r["lon"]), num(r["lat"]))
            rp = renta.get(cs) if cs else None
            r["seccion"] = cs
            r["renta_idx_seccion"] = round(100 * rp / base) if rp and base else None
    from statistics import median
    gb, gm = defaultdict(list), defaultdict(list)
    for r in recs:
        if r["renta_idx_seccion"] is not None:
            gb[(r["locality"], r["neighborhood"] or r["municipality"])].append(r["renta_idx_seccion"])
            gm[(r["locality"], r["municipality"])].append(r["renta_idx_seccion"])
    for r in recs:
        g = gb.get((r["locality"], r["neighborhood"] or r["municipality"]))
        if not g or len(g) < 5:  # barrio con pocos pisos: se usa su distrito/zona de Fotocasa
            g = gm.get((r["locality"], r["municipality"])) or g
        r["renta_idx"] = round(median(g)) if g else None
        r["nivel_zona"] = nivel(r["renta_idx"])
        r["in_scope"] = in_scope(r, scope)
    # Duplicados: el mismo piso publicado varias veces (misma agencia o distintas). Mismo punto (~10 m), superficie,
    # habitaciones, baños y planta, y precio a menos de un 1 % entre sí (se encadena de menor a mayor precio).
    def kgeo(r):
        la, lo = num(r["lat"]), num(r["lon"])
        return (round(la, 4) if la else None, round(lo, 4) if lo else None, r["surface"], r["rooms"], r["bathrooms"], r["floor"], r["subtype"])
    groups = defaultdict(list)
    for r in recs:
        groups[kgeo(r)].append(r)
    for r in recs:
        r["dup_n"], r["dup_group"] = 1, r["id"]
    for g in groups.values():
        if len(g) < 2 or g[0]["lat"] in ("", None):
            continue
        g.sort(key=lambda r: r["price_last"])
        cl = [[g[0]]]
        for r in g[1:]:
            if r["price_last"] <= cl[-1][-1]["price_last"] * 1.01:
                cl[-1].append(r)
            else:
                cl.append([r])
        for c in cl:
            # principal: el que sigue activo y, entre ellos, el de id más bajo
            main = min(c, key=lambda r: (r["state"] != "activo", int(r["id"])))
            for r in c:
                r["dup_n"], r["dup_group"] = len(c), main["id"]
    # En ámbito solo entra el principal de cada grupo de duplicados
    for r in recs:
        if r["in_scope"] and r["dup_group"] != r["id"]:
            r["in_scope"] = 0
    recs.sort(key=lambda r: (r["state"], r["price_last"]))
    out = ROOT / "data/clean"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{sid}.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(recs)
    from collections import Counter as C
    print(f"[{sid}] {len(recs)} anuncios ({sum(r['in_scope'] for r in recs)} en ámbito): {dict(C(r['state'] for r in recs))}")


if __name__ == "__main__":
    cfg = yaml.safe_load(open(Path(__file__).with_name("pisos.yml"), encoding="utf-8"))["searches"]
    for s in cfg:
        if len(sys.argv) < 2 or sys.argv[1] == s["id"]:
            build(s["id"], s.get("scope"))
