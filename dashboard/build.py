"""Genera dashboard/site/data.json (y copia index.html) desde los clean/raw de pisos y second-hand.

Uso (desde la raíz del repo): python3 dashboard/build.py
Solo lee; no toca nada de los módulos.
"""
import glob
import json
import os
import shutil
from datetime import datetime, timezone

import pandas as pd

import model as price_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dashboard", "site")
# Pablo: un anuncio "borrado" casi seguro se vendio, asi que cuenta como vendido probable en el dashboard.
PAID_STATES = ["vendido", "vendido_probable", "reservado", "borrado"]


def num(x):
    return None if pd.isna(x) else float(x)


def pct(s, q):
    s = s.dropna()
    return float(s.quantile(q)) if len(s) else None


def stats(s):
    s = s.dropna()
    return {"n": int(len(s)), "p25": pct(s, .25), "p50": pct(s, .5), "p75": pct(s, .75)}


def daily_latest(raw_glob):
    """Una foto por día (la última ejecución de ese día). Devuelve {fecha: df}."""
    by_day = {}
    for f in sorted(glob.glob(raw_glob)):
        day = os.path.basename(f)[:8]
        by_day[day] = f  # sorted -> la última del día gana
    return {f"{d[:4]}-{d[4:6]}-{d[6:]}": pd.read_csv(f) for d, f in by_day.items()}


FLAG_RE = {
    "terraza": r"(?<!sin )\bterraza",
    "balcon": r"(?<!sin )\bbalc[oó]n",
    "patio_jardin": r"(?<!sin )\b(patio|jard[ií]n)",
    "trastero": r"(?<!sin )\btrastero",
    "aire": r"aire acondicionado|a/a\b|climatizaci[oó]n",
    "piscina": r"(?<!sin )\bpiscina",
    "luminoso": r"luminos",
    "reformado": r"reformad[oa]|rehabilitad[oa]",
}


def listing_flags(ids):
    """Etiquetas por anuncio: texto de la descripcion (aproximado) + campos estructurados de Fotocasa."""
    import re
    rx = {k: re.compile(v) for k, v in FLAG_RE.items()}
    last = {}
    with open(os.path.join(ROOT, "pisos/data/raw/items.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d["id"] in ids:
                last[d["id"]] = d["item"]
    det = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "pisos/data/raw/*_details.csv"))):
        for r in pd.read_csv(f, usecols=["id", "features"]).itertuples():
            det[r.id] = r.features
    out = {}
    for i in ids:
        flags = set()
        it = last.get(i)
        if isinstance(it, str):
            it = json.loads(it)
        if it:
            t = (it.get("description") or "").lower()
            for k, r in rx.items():
                if r.search(t):
                    flags.add(k)
            dyn = it.get("dynamicFeatures") or []
            if "HAS_VIEW_TO_BEACH" in dyn:
                flags.add("vista_mar")
            if "IS_SELLING_URGENT" in dyn:
                flags.add("urgente")
        for x in json.loads(det[i]) if isinstance(det.get(i), str) else []:
            if x["type"] == "ELEVATOR" and x["value"] == "YES":
                flags.add("ascensor")
            if x["type"] == "PARKING":
                flags.add("parking")
            if x["type"] == "FURNISHED" and x["value"] == "YES":
                flags.add("amueblado")
        out[i] = sorted(flags)
    return out


def build_pisos():
    c = pd.read_csv(os.path.join(ROOT, "pisos/data/clean/pisos-bcn-norte.csv"))
    sc = c[c.in_scope == 1].copy()
    act = sc[sc.state == "activo"]
    ids = set(sc.id)
    flags = listing_flags(ids)

    # --- modelo de precio justo (solo anuncios activos) ---
    det = price_model.load_details(ids, sorted(glob.glob(os.path.join(ROOT, "pisos/data/raw/*_details.csv"))))
    d = sc[(sc.state == "activo") & sc.surface.between(30, 250) & sc.price_last.notna()].copy()
    d = d.set_index("id")
    d["f"] = [flags[i] for i in d.index]
    for col in ["FLOOR", "ANTIQUITY", "CONSERVATION_STATE"]:
        d[col] = [det.get(i, {}).get(col) for i in d.index]
    d["bkey"] = [price_model.barrio_key(n, m) for n, m in zip(d.neighborhood, d.municipality)]
    mdl, _mkt, oof = price_model.fit(d)

    # historico: por dia, [id, eur_m2] de los anuncios en ambito (el cliente filtra por id)
    hist = {}
    for day, df in daily_latest(os.path.join(ROOT, "pisos/data/raw/*_search.csv")).items():
        df = df[df.id.isin(ids)]
        eur = (df.price / df.surface).where(df.surface > 0)
        hist[day] = [[int(i), None if pd.isna(e) else int(round(e))] for i, e in zip(df.id, eur)]

    med = act.groupby("neighborhood").eur_m2.median().to_dict()
    today = c.first_seen.max()
    rows = []
    for r in sc.itertuples():
        m = med.get(r.neighborhood)
        rel = None if (pd.isna(r.eur_m2) or not m) else round((r.eur_m2 / m - 1) * 100, 1)
        fair = oof.get(r.id) if r.id in oof.index else None
        disc = None if fair is None else round((r.price_last / fair - 1) * 100, 1)
        warn = []
        if r.a_reformar == 1:
            warn.append("a reformar")
        if r.rented == 1:
            warn.append("alquilado")
        if int(r.plantilla or 0):
            warn.append("ficha repetida por agencias")
        if disc is not None and disc <= -30:
            warn.append("muy por debajo: revisar (error, defecto u oferta falsa)")
        if mdl["n_barrio"].get(price_model.barrio_key(r.neighborhood, r.municipality), 0) < 5:
            warn.append("pocos datos del barrio")
        rows.append({"id": int(r.id), "a": int(r.state == "activo"),
                     "fair": None if fair is None else int(round(fair, -2)), "disc": disc, "warn": warn, "ret": int(r.state == "retirado"),
                     "fs": r.first_seen, "ls": r.last_seen, "new": int(r.first_seen == today),
                     "url": r.url, "barrio": r.neighborhood, "mun": r.municipality,
                     "price": num(r.price_last), "eur_m2": num(r.eur_m2), "m2": num(r.surface),
                     "rooms": num(r.rooms), "drop": num(r.drop_pct), "days": num(r.days_listed),
                     "chg": num(r.price_changes), "plantilla": int(r.plantilla or 0), "rel": rel,
                     "ext": int(r.exterior == 1) if not pd.isna(r.exterior) else None,
                     "lat": num(r.lat), "lon": num(r.lon), "f": flags[r.id]})
    return {"retirados": int((c.state == "retirado").sum()), "hist": hist, "rows": rows, "model": mdl}


def build_sh():
    prods = {}
    days = daily_latest(os.path.join(ROOT, "second-hand/data/raw/*_search.csv"))
    for f in sorted(glob.glob(os.path.join(ROOT, "second-hand/data/clean/*.csv"))):
        name = os.path.basename(f)[:-4]
        c = pd.read_csv(f)
        ids = set(c.id)
        hist = {}
        for day, df in days.items():
            df = df[(df["product"] == name) & df.id.isin(ids)]
            hist[day] = [[i, num(p)] for i, p in zip(df.id, df.price)]
        today = c.first_seen.max()
        g = lambda r, k: None if not hasattr(r, k) or pd.isna(getattr(r, k)) else getattr(r, k)
        rows = []
        for r in c.itertuples():
            rows.append({"id": r.id, "url": r.url, "title": r.title, "state": r.state, "sc": int(r.in_scope),
                         "paid": int(r.state in PAID_STATES), "new": int(r.first_seen == today),
                         "price": num(r.price_last), "final": num(r.price_final), "days": num(r.days_listed),
                         "chg": num(r.price_changes), "seller": r.seller_type, "dup": num(r.dup_n) or 1,
                         "is_new": int(r.is_new) if not pd.isna(r.is_new) else 0,
                         "views_d": g(r, "views_por_dia"), "km": g(r, "km"), "year": g(r, "year"),
                         "a2": g(r, "a2"), "variant": g(r, "variant"), "cond": g(r, "condition"),
                         "region": g(r, "region"), "abs": int(bool(g(r, "abs"))), "qs": int(bool(g(r, "quickshifter")))})
        prods[name] = {"rows": rows, "hist": hist}
    return prods


def clean_nan(o):
    """NaN no es JSON valido: lo pasamos a null (el navegador no puede parsearlo)."""
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, dict):
        return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean_nan(v) for v in o]
    return o


def main():
    os.makedirs(OUT, exist_ok=True)
    data = clean_nan({"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                      "pisos": build_pisos(), "sh": build_sh()})
    with open(os.path.join(OUT, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    shutil.copy(os.path.join(ROOT, "dashboard", "index.html"), os.path.join(OUT, "index.html"))
    shutil.copytree(os.path.join(ROOT, "dashboard", "vendor"), os.path.join(OUT, "vendor"), dirs_exist_ok=True)
    print("ok", os.path.getsize(os.path.join(OUT, "data.json")) // 1024, "KB")


if __name__ == "__main__":
    main()
