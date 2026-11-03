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


def build_pisos():
    c = pd.read_csv(os.path.join(ROOT, "pisos/data/clean/pisos-bcn-norte.csv"))
    sc = c[c.in_scope == 1]
    act = sc[sc.state == "activo"].copy()
    ids = set(sc.id)

    series = []
    for day, df in daily_latest(os.path.join(ROOT, "pisos/data/raw/*_search.csv")).items():
        df = df[df.id.isin(ids)]
        eur = (df.price / df.surface).where(df.surface > 0)
        series.append({"date": day, "n": int(len(df)), "eur_m2": pct(eur, .5), "price": pct(df.price, .5)})

    grp = act.groupby("neighborhood")
    barrios = []
    med = {}
    for name, g in grp:
        med[name] = g.eur_m2.median()
        barrios.append({"name": name, "mun": g.municipality.iloc[0], "n": int(len(g)),
                        "eur_m2": num(g.eur_m2.median()), "price": num(g.price_last.median()),
                        "renta": num(g.renta_idx.median())})
    barrios.sort(key=lambda b: -b["n"])

    today = c.first_seen.max()
    rows = []
    for r in act.itertuples():
        m = med.get(r.neighborhood)
        rel = None if (pd.isna(r.eur_m2) or not m) else round((r.eur_m2 / m - 1) * 100, 1)
        rows.append({"id": int(r.id), "url": r.url, "barrio": r.neighborhood, "mun": r.municipality,
                     "price": num(r.price_last), "eur_m2": num(r.eur_m2), "m2": num(r.surface),
                     "rooms": num(r.rooms), "drop": num(r.drop_pct), "days": num(r.days_listed),
                     "chg": num(r.price_changes), "plantilla": int(r.plantilla or 0), "rel": rel,
                     "lat": num(r.lat), "lon": num(r.lon)})
    return {
        "kpis": {"activos": int(len(act)), "nuevos_hoy": int((act.first_seen == today).sum()),
                 "bajadas": int((act.drop_pct > 0).sum()),
                 "retirados": int((c.state == "retirado").sum()),
                 "eur_m2": num(act.eur_m2.median()), "price": num(act.price_last.median())},
        "series": series, "barrios": barrios, "rows": rows,
    }


def build_sh():
    prods = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "second-hand/data/clean/*.csv"))):
        name = os.path.basename(f)[:-4]
        c = pd.read_csv(f)
        sc = c[c.in_scope == 1]
        act = sc[sc.state == "activo"]
        paid = sc[sc.state.isin(PAID_STATES)]
        ids = set(sc.id)
        series = []
        for day, df in daily_latest(os.path.join(ROOT, "second-hand/data/raw/*_search.csv")).items():
            df = df[(df["product"] == name) & df.id.isin(ids)]
            series.append({"date": day, "n": int(len(df)), "price": pct(df.price, .5)})
        today = c.first_seen.max()
        rows = []
        for r in sc.sort_values("price_last").itertuples():
            rows.append({"url": r.url, "title": r.title, "state": r.state, "price": num(r.price_last),
                         "final": num(r.price_final), "days": num(r.days_listed),
                         "chg": num(r.price_changes), "seller": r.seller_type,
                         "views_d": num(getattr(r, "views_por_dia", None)),
                         "fav": num(getattr(r, "fav_por_visita_last", None)),
                         "km": num(getattr(r, "km", None)), "year": num(getattr(r, "year", None)),
                         "city": r.city})
        prods[name] = {"asks": stats(act.price_last), "paid": stats(paid.price_final.fillna(paid.price_last)),
                       "n_scope": int(len(sc)), "n_active": int(len(act)),
                       "nuevos_hoy": int((act.first_seen == today).sum()),
                       "vendidos": int(paid.shape[0]), "series": series, "rows": rows}
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
