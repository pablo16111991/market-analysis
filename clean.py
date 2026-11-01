#!/usr/bin/env python3
"""Limpieza: lee TODO lo crudo de data/<producto>/raw/ y genera data/<producto>/clean.csv
(una fila por anuncio con su último estado). Se puede rehacer siempre desde lo crudo.

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
from extract import features, norm

COLS = ["id", "url", "title", "state", "state_date", "price_first", "price_last", "price_final", "price_changes",
        "reserved_ever", "brand", "model", "variant", "cc", "year", "year_src", "km", "km_src", "abs", "flags",
        "dealer", "seller_listings", "dup_n", "city", "created_at", "first_seen", "last_seen", "days_listed",
        "runs_seen", "views", "favorites", "desc_start"]


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def clean_product(pdir):
    raw = pdir / "raw"
    search, details, status = read_all(raw, "search"), read_all(raw, "details"), read_all(raw, "status")
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
        f = features({"title": last["title"], "description": desc, "attrs": attrs})
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
            **{k: f[k] for k in ("brand", "model", "variant", "cc", "year", "year_src", "km", "km_src", "abs", "flags")},
            "dealer": int("posible_nueva" in f["flags"]), "seller_listings": per_seller[last["user_id"]],
            "city": last["city"], "created_at": last["created_at"][:10], "first_seen": first["seen_at"][:10],
            "last_seen": last["seen_at"][:10], "days_listed": days, "runs_seen": len(rows),
            "views": (s or {}).get("views") or (d or {}).get("views"),
            "favorites": (s or {}).get("favorites") or (d or {}).get("favorites"),
            "desc_start": desc.replace("\n", " ")[:140],
        })
    # Duplicados: mismos título+precio+km+año (concesionarios que repiten el anuncio)
    key = lambda r: (re.sub(r"[^a-z0-9]", "", norm(r["title"])), r["price_last"], r["km"], r["year"])
    dups = Counter(key(r) for r in recs)
    for r in recs:
        r["dup_n"] = dups[key(r)]
    recs.sort(key=lambda r: (r["state"], r["price_last"] or 0))
    with open(pdir / "clean.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(recs)
    print(f"[{pdir.name}] {len(recs)} anuncios: {dict(Counter(r['state'] for r in recs))}")
    return len(recs)


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for pdir in sorted((ROOT / "data").glob("*/")):
        if pdir.is_dir() and (not only or pdir.name == only):
            clean_product(pdir)
