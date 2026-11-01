#!/usr/bin/env python3
"""Limpieza: lee TODO lo crudo de data/raw/ y genera, por producto,
en data/clean/<producto>.csv (una fila por anuncio con su último estado). Se puede rehacer siempre desde lo crudo.

Estado final de cada anuncio:
  vendido / caducado / borrado   confirmado al reconsultar su página cuando dejó de salir
  reservado / activo             sigue saliendo en la última búsqueda
  desaparecido                   dejó de salir y aún no está confirmado qué pasó
"""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from collect import ROOT, read_all
import yaml
from extract import features, features_generic, norm

BASE = ["id", "url", "title", "state", "state_date", "price_first", "price_last", "price_final", "price_changes",
        "reserved_ever", "condition", "is_new", "seller_type", "seller_listings", "dup_n", "city", "region",
        "distance_km", "created_at", "first_seen", "last_seen", "days_listed", "runs_seen", "views", "favorites",
        "desc_start"]
EXTRA = {
    "moto": ["brand", "model", "variant", "cc", "year", "year_src", "km", "km_src", "abs", "a2", "quickshifter", "flags"],
    "generic": ["brand", "model", "flags"],
}


def dist(r):
    """Km en línea recta desde Barcelona (Plaça Catalunya), si el anuncio trae coordenadas."""
    from math import asin, cos, radians, sin, sqrt
    try:
        la, lo = float(r["latitude"]), float(r["longitude"])
    except (KeyError, TypeError, ValueError):
        return ""
    la0, lo0 = radians(41.3868), radians(2.1700)
    a = sin((radians(la) - la0) / 2) ** 2 + cos(la0) * cos(radians(la)) * sin((radians(lo) - lo0) / 2) ** 2
    return round(2 * 6371 * asin(sqrt(a)))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def clean_product(pid, allraw, extractor="moto"):
    search, details, status = ([r for r in allraw[k] if r["product"] == pid] for k in ("search", "details", "status"))
    if not search:
        return 0
    last_run = max(r["run_id"] for r in search)
    by_id = defaultdict(list)
    for r in sorted(search, key=lambda r: r["run_id"]):
        by_id[r["id"]].append(r)
    det = {}
    for d in sorted(details, key=lambda r: r["fetched_at"]):
        det[d["id"]] = d
    st = {}
    for s in sorted(status, key=lambda r: r["checked_at"]):
        st[s["id"]] = s

    recs = []
    per_seller = Counter(rows[-1]["user_id"] for rows in by_id.values())
    for iid, rows in by_id.items():
        first, last = rows[0], rows[-1]
        desc = next((r["description"] for r in reversed(rows) if r["description"]), "")
        d, s = det.get(iid), st.get(iid)
        attrs = json.loads(d["attrs_json"]) if d and d.get("attrs_json") else {}
        fx = features if extractor == "moto" else features_generic
        f = fx({"title": last["title"], "description": desc, "attrs": attrs})
        prices = [num(r["price"]) for r in rows]
        changes = sum(1 for a, b in zip(prices, prices[1:]) if a != b)
        seen_last = last["run_id"] == last_run
        if s and s["final"] == "1":
            state = "borrado" if s["http_status"] == "404" else "vendido" if s["sold"] == "1" else "caducado"
            state_date = s["checked_at"][:10]
        elif seen_last:
            state, state_date = ("reservado" if last["reserved"] == "1" else "activo"), last["seen_at"][:10]
        else:
            state, state_date = "desaparecido", last["seen_at"][:10]
        price_final = num(s["price"]) if state == "vendido" and s and num(s["price"]) else prices[-1]
        end = state_date if state not in ("activo", "reservado") else last["seen_at"][:10]
        try:
            from datetime import date
            days = (date.fromisoformat(end) - date.fromisoformat(last["created_at"][:10])).days
        except ValueError:
            days = ""
        recs.append({
            "id": iid, "url": f"https://es.wallapop.com/item/{last['web_slug']}", "title": last["title"],
            "state": state, "state_date": state_date, "price_first": prices[0], "price_last": prices[-1],
            "price_final": price_final, "price_changes": changes,
            "reserved_ever": int(any(r["reserved"] == "1" for r in rows)),
            **{k: f.get(k) for k in EXTRA[extractor]}, "condition": f.get("condition"),
            "is_new": int("posible_nueva" in f["flags"]),
            "seller_type": "tienda" if f["shop_signals"] >= 1 or per_seller[last["user_id"]] >= 3 else "particular",
            "seller_listings": per_seller[last["user_id"]],
            "city": last["city"], "region": last.get("region"), "distance_km": dist(last), "created_at": last["created_at"][:10], "first_seen": first["seen_at"][:10],
            "last_seen": last["seen_at"][:10], "days_listed": days, "runs_seen": len(rows),
            "views": (s or {}).get("views") or (d or {}).get("views"),
            "favorites": (s or {}).get("favorites") or (d or {}).get("favorites"),
            "desc_start": desc.replace("\n", " ")[:140],
        })
    # Duplicados: mismos título+precio+km+año (concesionarios que repiten el anuncio)
    key = lambda r: (re.sub(r"[^a-z0-9]", "", norm(r["title"])), r["price_last"], r.get("km"), r.get("year"))
    dups = Counter(key(r) for r in recs)
    for r in recs:
        r["dup_n"] = dups[key(r)]
    recs.sort(key=lambda r: (r["state"], r["price_last"] or 0))
    out = ROOT / "data" / "clean"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{pid}.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=BASE + EXTRA[extractor])
        w.writeheader()
        w.writerows(recs)
    print(f"[{pid}] {len(recs)} anuncios: {dict(Counter(r['state'] for r in recs))}")
    return len(recs)


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cfg = {p["id"]: p for p in yaml.safe_load(open(ROOT / "products.yml", encoding="utf-8"))["products"]}
    raw = ROOT / "data" / "raw"
    allraw = {k: read_all(raw, k) for k in ("search", "details", "status")}
    for pid in sorted({r["product"] for r in allraw["search"]}):
        if not only or pid == only:
            clean_product(pid, allraw, cfg.get(pid, {}).get("extractor", "generic"))
