#!/usr/bin/env python3
"""Descarga CRUDA de Wallapop. Solo añade ficheros; nunca modifica lo anterior.

Cada ejecución (run_id) escribe en data/raw/ (todos los productos juntos, columna `product`):
  <run_id>_search.csv   anuncios vistos en la búsqueda (precio, reservado, título, descripción…)
  <run_id>_details.csv  atributos estructurados (año, km, marca…) de anuncios nuevos, mientras están activos
  <run_id>_status.csv   estado de anuncios que ya no salen en búsqueda (vendido/caducado/borrado/activo)
  <run_id>_counters.csv foto diaria de visitas/favoritos/conversaciones/precio/reservado de los activos en ámbito

Uso: python collect.py [--only ID] [--run-id X] [--limit 150]
"""
import argparse
import csv
import json
import random
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).parent
API = "https://api.wallapop.com/api/v3/search/section"
HEADERS = {
    "X-DeviceOS": "0", "Accept": "application/json", "Accept-Language": "es-ES,es;q=0.9",
    "Origin": "https://es.wallapop.com", "Referer": "https://es.wallapop.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
}
SEARCH_COLS = ["run_id", "product", "seen_at", "id", "user_id", "title", "description", "price", "currency",
               "reserved", "category_id", "city", "region", "postal_code", "latitude", "longitude", "shippable", "created_at",
               "modified_at", "web_slug"]
DETAIL_COLS = ["run_id", "product", "fetched_at", "id", "condition", "views", "favorites", "conversations",
               "brand", "model", "year", "km", "attrs_json"]
COUNTER_COLS = ["run_id", "product", "fetched_at", "id", "views", "favorites", "conversations", "price", "reserved"]
STATUS_COLS = ["run_id", "product", "checked_at", "id", "http_status", "sold", "expired", "reserved", "price",
               "condition", "views", "favorites", "modified_at", "final"]


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds") if ms else ""


def to_int(x):
    try:
        return int(float(str(x).replace(".", "").replace(",", "")))
    except (TypeError, ValueError):
        return ""


def write_csv(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def read_all(raw_dir, kind):
    """Lee todos los ficheros crudos de un tipo, ordenados por run_id."""
    out = []
    for p in sorted(raw_dir.glob(f"*_{kind}.csv")):
        with open(p, newline="", encoding="utf-8") as fh:
            out.extend(csv.DictReader(fh))
    return out


def parse_item_page(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None

    def find(o):
        if isinstance(o, dict):
            if "flags" in o and "price" in o:
                return o
            for v in o.values():
                if (r := find(v)):
                    return r
        elif isinstance(o, list):
            for v in o:
                if (r := find(v)):
                    return r
        return None

    return find(json.loads(m.group(1)))


def search(client, p, run_id, now):
    params = {"keywords": p["query"], "source": "search_box", "search_id": str(uuid.uuid4()),
              "latitude": p.get("lat", 41.3768), "longitude": p.get("lon", 2.1669),
              "order_by": "most_relevance", "search_country": "ES",
              "search_section": "organic_search_results", "section_type": "organic_search_results"}
    if p.get("category"):
        params["category_id"] = p["category"]
    if p.get("min_price"):
        params["min_sale_price"] = p["min_price"]
    if p.get("max_price"):
        params["max_sale_price"] = p["max_price"]
    if p.get("distance_km"):
        params["distance_in_km"] = p["distance_km"]
    rows, seen, empty = [], set(), 0
    for page in range(1, int(p.get("max_pages", 12)) + 1):
        r = client.get(API, params=params)
        if r.status_code == 403:
            sys.exit("403 de Wallapop/CloudFront (¿VPN o IP bloqueada?)")
        r.raise_for_status()
        j = r.json()
        items = ((j.get("data") or {}).get("section") or {}).get("items") or []
        for it in items:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            loc, price = it.get("location") or {}, it.get("price") or {}
            rows.append({
                "run_id": run_id, "product": p["id"], "seen_at": now, "id": it["id"], "user_id": it.get("user_id"),
                "title": it.get("title"), "description": it.get("description"), "price": price.get("amount"),
                "currency": price.get("currency"), "reserved": int(bool((it.get("reserved") or {}).get("flag"))),
                "category_id": it.get("category_id"), "city": loc.get("city"), "region": loc.get("region"),
                "postal_code": loc.get("postal_code"),
                "latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
                "shippable": int(bool((it.get("shipping") or {}).get("item_is_shippable"))),
                "created_at": ms_to_iso(it.get("created_at")), "modified_at": ms_to_iso(it.get("modified_at")),
                "web_slug": it.get("web_slug"),
            })
        nxt = (j.get("meta") or {}).get("next_page")
        empty = empty + 1 if not items else 0  # Wallapop filtra después de paginar: hay páginas vacías en medio
        if not nxt or empty >= 5:
            break
        params["next_page"] = nxt
        time.sleep(random.uniform(1.5, 3.0))
    return rows


def fetch_details(client, product, run_id, ids):
    rows = []
    for iid in ids:
        r = client.get(f"https://api.wallapop.com/api/v3/items/{iid}")
        if r.status_code != 200:
            continue
        j = r.json()
        c = j.get("counters") or {}
        ta = j.get("type_attributes") or {}
        attrs = {k: (v or {}).get("value") for k, v in ta.items() if isinstance(v, dict)}
        rows.append({"run_id": run_id, "product": product, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "id": iid, "condition": attrs.get("condition"), "views": c.get("views"),
                     "favorites": c.get("favorites"), "conversations": c.get("conversations"),
                     "brand": attrs.get("brand"), "model": attrs.get("model"), "year": to_int(attrs.get("year")),
                     "km": to_int(attrs.get("km")), "attrs_json": json.dumps(attrs, ensure_ascii=False)})
        time.sleep(random.uniform(1.0, 2.0))
    return rows


def scope_ids(product):
    """Ids en ámbito y activos según el último clean (si no existe aún, vacío)."""
    p = ROOT / "data" / "clean" / f"{product}.csv"
    if not p.exists():
        return set()
    with open(p, newline="", encoding="utf-8-sig") as fh:
        return {r["id"] for r in csv.DictReader(fh) if r.get("in_scope") == "1"}


def fetch_counters(client, product, run_id, ids):
    """Foto diaria de visitas/favoritos/conversaciones/precio/reservado (solo se añade)."""
    rows = []
    for iid in ids:
        try:
            r = client.get(f"https://api.wallapop.com/api/v3/items/{iid}")
            if r.status_code != 200:
                continue
            j = r.json()
        except (httpx.HTTPError, ValueError):
            continue
        c = j.get("counters") or {}
        price = ((j.get("price") or {}).get("cash") or {}).get("amount")
        rows.append({"run_id": run_id, "product": product, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "id": iid, "views": c.get("views"), "favorites": c.get("favorites"),
                     "conversations": c.get("conversations"), "price": price,
                     "reserved": int(bool((j.get("reserved") or {}).get("flag")))})
        time.sleep(random.uniform(1.0, 2.0))
    return rows


def check_status(client, product, run_id, items):
    rows = []
    for iid, slug in items:
        if not slug:
            continue
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        r = client.get(f"https://es.wallapop.com/item/{slug}", headers={"Accept": "text/html"}, follow_redirects=True)
        base = {"run_id": run_id, "product": product, "checked_at": now, "id": iid}
        if r.status_code == 404:
            rows.append({**base, "http_status": 404, "final": 1})
        elif r.status_code == 200 and (it := parse_item_page(r.text)):
            fl = it.get("flags") or {}
            rows.append({**base, "http_status": 200, "sold": int(bool(fl.get("sold"))),
                         "expired": int(bool(fl.get("expired"))), "reserved": int(bool(fl.get("reserved"))),
                         "price": ((it.get("price") or {}).get("cash") or {}).get("amount"),
                         "condition": (it.get("condition") or {}).get("value"), "views": it.get("views"),
                         "favorites": it.get("favorites"), "modified_at": ms_to_iso(it.get("modifiedDate")),
                         "final": int(bool(fl.get("sold") or fl.get("expired")))})
        time.sleep(random.uniform(1.5, 3.0))
    return rows


def run_product(client, p, run_id, limit, prev):
    """Devuelve (search_rows, detail_rows, status_rows, counter_rows) de este producto."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    mine = lambda rows: [r for r in rows if r["product"] == p["id"]]
    prev_search, prev_status, prev_details = (mine(prev[k]) for k in ("search", "status", "details"))

    rows = search(client, p, run_id, now)
    print(f"[{p['id']}] búsqueda: {len(rows)} anuncios")
    if not rows:
        sys.exit(f"[{p['id']}] búsqueda vacía: no se guarda nada (posible bloqueo)")
    today = {r["id"] for r in rows}

    # Detalles (año, km…) de los anuncios que aún no tienen, mientras están activos
    have = {r["id"] for r in prev_details}
    new_ids = [r["id"] for r in rows if r["id"] not in have][:limit]
    det = fetch_details(client, p["id"], run_id, new_ids)
    print(f"[{p['id']}] detalles nuevos: {len(det)}")

    # Foto diaria de contadores: anuncios activos en ámbito (los nuevos ya traen sus contadores en det)
    newc = {d["id"]: d for d in det}
    cnt = [{"run_id": run_id, "product": p["id"], "fetched_at": d["fetched_at"], "id": d["id"], "views": d["views"],
            "favorites": d["favorites"], "conversations": d["conversations"], "price": "", "reserved": ""} for d in det]
    pend = [i for i in sorted(scope_ids(p["id"]) & today) if i not in newc]
    cnt += fetch_counters(client, p["id"], run_id, pend)
    print(f"[{p['id']}] contadores: {len(cnt)}")

    # Anuncios vistos antes que hoy no aparecen y aún no tienen estado final -> comprobar su página
    final = {r["id"] for r in prev_status if r.get("final") == "1"}
    slugs = {r["id"]: r["web_slug"] for r in prev_search}
    todo = [(i, slugs[i]) for i in slugs if i not in today and i not in final][:limit]
    st = check_status(client, p["id"], run_id, todo)
    kinds = {"vendido": 0, "caducado": 0, "borrado": 0, "activo": 0}
    for s in st:
        kinds["borrado" if s["http_status"] == 404 else "vendido" if s.get("sold") else "caducado" if s.get("expired") else "activo"] += 1
    print(f"[{p['id']}] desaparecidos comprobados: {len(st)} {kinds}")
    return rows, det, st, cnt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="id de un producto de products.yml")
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    ap.add_argument("--limit", type=int, default=150, help="máx. detalles y comprobaciones por producto y ejecución")
    a = ap.parse_args()
    prods = yaml.safe_load(open(ROOT / "products.yml", encoding="utf-8"))["products"]
    raw = ROOT / "data" / "raw"
    prev = {k: read_all(raw, k) for k in ("search", "details", "status")}
    out = {"search": [], "details": [], "status": [], "counters": []}
    with httpx.Client(headers=HEADERS, timeout=20, http2=False) as client:
        for p in prods:
            if a.only and p["id"] != a.only:
                continue
            for k, rows in zip(("search", "details", "status", "counters"), run_product(client, p, a.run_id, a.limit, prev)):
                out[k].extend(rows)
    for k, cols in (("search", SEARCH_COLS), ("details", DETAIL_COLS), ("status", STATUS_COLS), ("counters", COUNTER_COLS)):
        if out[k]:
            write_csv(raw / f"{a.run_id}_{k}.csv", cols, out[k])


if __name__ == "__main__":
    main()
