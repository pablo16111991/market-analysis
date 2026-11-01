#!/usr/bin/env python3
"""Wallapop scraper -> SQLite.

Uso:
  pip install httpx
  python scrape.py "nux mg-30"
  python scrape.py "guitarra electrica" --max-pages 10 --order newest

Guarda cada anuncio (con el JSON crudo) en wallapop.db y un snapshot de precio
por ejecución, para poder ver cambios de precio y anuncios que desaparecen.
"""
import argparse
import json
import random
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone

import httpx

API = "https://api.wallapop.com/api/v3/search/section"
DB_PATH = "wallapop.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  title TEXT, description TEXT,
  price REAL, currency TEXT,
  category_id INTEGER, taxonomy TEXT,
  city TEXT, region TEXT, postal_code TEXT, lat REAL, lon REAL,
  shippable INTEGER, reserved INTEGER,
  created_at TEXT, modified_at TEXT,
  web_slug TEXT, user_id TEXT,
  raw TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
  item_id TEXT NOT NULL,
  seen_at TEXT NOT NULL,
  price REAL, reserved INTEGER, query TEXT,
  PRIMARY KEY (item_id, seen_at)
);
CREATE TABLE IF NOT EXISTS runs (
  seen_at TEXT PRIMARY KEY, query TEXT, order_by TEXT, n_items INTEGER
);
CREATE INDEX IF NOT EXISTS idx_items_last_seen ON items(last_seen);
CREATE TABLE IF NOT EXISTS item_status (
  item_id TEXT NOT NULL, checked_at TEXT NOT NULL, http_status INTEGER,
  sold INTEGER, expired INTEGER, reserved INTEGER,
  price REAL, condition TEXT, views INTEGER, favorites INTEGER, modified_at TEXT,
  final INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (item_id, checked_at)
);
CREATE TABLE IF NOT EXISTS item_details (
  item_id TEXT PRIMARY KEY, fetched_at TEXT,
  condition TEXT, views INTEGER, favorites INTEGER, conversations INTEGER,
  attrs TEXT, brand TEXT, model TEXT, year INTEGER, km INTEGER
);
"""

# Anuncios que estaban en la última búsqueda de su query y ya no salen, sin estado final.
GONE_SQL = """
SELECT i.id, i.web_slug FROM items i
JOIN (SELECT item_id, query, MAX(seen_at) AS last FROM snapshots GROUP BY item_id) l ON l.item_id = i.id
WHERE l.last < (SELECT MAX(seen_at) FROM runs r WHERE r.query = l.query)
  AND NOT EXISTS (SELECT 1 FROM item_status st WHERE st.item_id = i.id AND st.final = 1)
LIMIT ?
"""


def ms_to_iso(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def upsert(db, it, now, query):
    price = (it.get("price") or {}).get("amount")
    loc = it.get("location") or {}
    ship = it.get("shipping") or {}
    reserved = int(bool((it.get("reserved") or {}).get("flag")))
    tax = [t.get("name") for t in (it.get("taxonomy") or [])]
    db.execute(
        """INSERT INTO items (id, first_seen, last_seen, title, description, price, currency,
             category_id, taxonomy, city, region, postal_code, lat, lon, shippable, reserved,
             created_at, modified_at, web_slug, user_id, raw)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             last_seen=excluded.last_seen, title=excluded.title, description=excluded.description,
             price=excluded.price, reserved=excluded.reserved, modified_at=excluded.modified_at,
             shippable=excluded.shippable, raw=excluded.raw""",
        (
            it["id"], now, now, it.get("title"), it.get("description"), price,
            (it.get("price") or {}).get("currency"), it.get("category_id"),
            json.dumps(tax, ensure_ascii=False), loc.get("city"), loc.get("region"),
            loc.get("postal_code"), loc.get("latitude"), loc.get("longitude"),
            int(bool(ship.get("item_is_shippable"))), reserved,
            ms_to_iso(it.get("created_at")), ms_to_iso(it.get("modified_at")),
            it.get("web_slug"), it.get("user_id"), json.dumps(it, ensure_ascii=False),
        ),
    )
    db.execute(
        "INSERT OR IGNORE INTO snapshots (item_id, seen_at, price, reserved, query) VALUES (?,?,?,?,?)",
        (it["id"], now, price, reserved, query),
    )


def parse_item_page(html):
    """Saca el anuncio del JSON embebido (__NEXT_DATA__) de la página del item."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None

    def find(o):
        if isinstance(o, dict):
            if "flags" in o and "price" in o:
                return o
            for v in o.values():
                r = find(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v)
                if r:
                    return r
        return None

    return find(json.loads(m.group(1)))


def check_gone(db, client, limit):
    rows = db.execute(GONE_SQL, (limit,)).fetchall()
    print(f"{len(rows)} anuncios ya no aparecen en búsqueda; reconsultando…")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    counts = {"vendido": 0, "caducado": 0, "borrado": 0, "activo": 0, "error": 0}
    for iid, slug in rows:
        if not slug:
            continue
        r = client.get(f"https://es.wallapop.com/item/{slug}", headers={"Accept": "text/html"},
                       follow_redirects=True)
        if r.status_code == 404:
            db.execute("INSERT OR REPLACE INTO item_status (item_id, checked_at, http_status, final) VALUES (?,?,?,1)",
                       (iid, now, 404))
            counts["borrado"] += 1
        elif r.status_code == 200 and (it := parse_item_page(r.text)):
            fl = it.get("flags") or {}
            cond = (it.get("condition") or {}).get("value")
            final = int(bool(fl.get("sold") or fl.get("expired")))
            db.execute(
                "INSERT OR REPLACE INTO item_status VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, now, 200, int(bool(fl.get("sold"))), int(bool(fl.get("expired"))),
                 int(bool(fl.get("reserved"))), ((it.get("price") or {}).get("cash") or {}).get("amount"),
                 cond, it.get("views"), it.get("favorites"), ms_to_iso(it.get("modifiedDate")), final),
            )
            counts["vendido" if fl.get("sold") else "caducado" if fl.get("expired") else "activo"] += 1
        else:
            counts["error"] += 1
        db.commit()
        time.sleep(random.uniform(1.5, 3.0))
    print(counts)


def fetch_details(db, client, limit):
    """Estado del producto y contadores (la búsqueda no los trae)."""
    rows = db.execute(
        "SELECT id FROM items WHERE id NOT IN (SELECT item_id FROM item_details) ORDER BY last_seen DESC LIMIT ?",
        (limit,)).fetchall()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    for (iid,) in rows:
        r = client.get(f"https://api.wallapop.com/api/v3/items/{iid}")
        if r.status_code != 200:
            continue
        j = r.json()
        c = j.get("counters") or {}
        ta = j.get("type_attributes") or {}
        attrs = {k: (v or {}).get("value") for k, v in ta.items() if isinstance(v, dict)}

        def to_int(x):
            try:
                return int(float(str(x).replace(".", "").replace(",", "")))
            except (TypeError, ValueError):
                return None

        db.execute("INSERT OR REPLACE INTO item_details VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (iid, now, attrs.get("condition"), c.get("views"), c.get("favorites"),
                    c.get("conversations"), json.dumps(attrs, ensure_ascii=False),
                    attrs.get("brand"), attrs.get("model"), to_int(attrs.get("year")),
                    to_int(attrs.get("km"))))
        db.commit()
        n += 1
        time.sleep(random.uniform(1.0, 2.0))
    print(f"detalles guardados: {n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--check-gone", action="store_true",
                    help="reconsulta los anuncios que ya no salen en búsqueda (vendido/caducado/borrado)")
    ap.add_argument("--details", action="store_true", help="guarda estado del producto y contadores")
    ap.add_argument("--limit", type=int, default=100, help="máximo de anuncios en --check-gone/--details")
    ap.add_argument("--max-pages", type=int, default=5)
    ap.add_argument("--order", default="most_relevance",
                    choices=["most_relevance", "newest", "closest", "price_low_to_high", "price_high_to_low"])
    ap.add_argument("--lat", type=float, default=41.3768)  # Barcelona
    ap.add_argument("--lon", type=float, default=2.1669)
    ap.add_argument("--country", default="ES")
    ap.add_argument("--category", type=int, help="category_id de Wallapop (motos: 14000)")
    ap.add_argument("--min-price", type=int, help="precio mínimo (filtro del servidor)")
    ap.add_argument("--max-price", type=int, help="precio máximo (filtro del servidor)")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    params = {
        "keywords": args.query,
        "source": "search_box",
        "search_id": str(uuid.uuid4()),
        "latitude": args.lat,
        "longitude": args.lon,
        "order_by": args.order,
        "search_country": args.country,
        "search_section": "organic_search_results",
        "section_type": "organic_search_results",
    }
    qlabel = args.query or ""
    if args.category:
        params["category_id"] = args.category
        qlabel += f"|cat={args.category}"
    if args.min_price:
        params["min_sale_price"] = args.min_price
        qlabel += f"|min={args.min_price}"
    if args.max_price:
        params["max_sale_price"] = args.max_price
        qlabel += f"|max={args.max_price}"
    headers = {
        "X-DeviceOS": "0",
        "Accept": "application/json",
        "Accept-Language": "es-ES,es;q=0.9",
        "Origin": "https://es.wallapop.com",
        "Referer": "https://es.wallapop.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    }

    if args.check_gone or args.details:
        with httpx.Client(headers=headers, timeout=20, http2=False) as client:
            if args.check_gone:
                check_gone(db, client, args.limit)
            if args.details:
                fetch_details(db, client, args.limit)
        return
    if not args.query:
        sys.exit("Falta la búsqueda: python scrape.py \"nux mg-30\"")

    total = 0
    empty = 0
    with httpx.Client(headers=headers, timeout=20, http2=False) as client:
        for page in range(1, args.max_pages + 1):
            r = client.get(API, params=params)
            if r.status_code == 403:
                sys.exit("403 de Wallapop/CloudFront: prueba sin VPN o desde otra red. "
                         "Si persiste, usa el userscript de Tampermonkey.")
            r.raise_for_status()
            j = r.json()
            items = ((j.get("data") or {}).get("section") or {}).get("items") or []
            for it in items:
                upsert(db, it, now, qlabel)
            db.commit()
            total += len(items)
            print(f"página {page}: {len(items)} anuncios")
            nxt = (j.get("meta") or {}).get("next_page")
            # Con filtros, Wallapop filtra después de paginar: puede haber páginas vacías en medio.
            empty = empty + 1 if not items else 0
            if not nxt or empty >= 5:
                break
            params["next_page"] = nxt
            time.sleep(random.uniform(1.5, 3.5))

    db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?)", (now, qlabel, args.order, total))
    db.commit()
    print(f"Total: {total} anuncios guardados en {args.db}")


if __name__ == "__main__":
    main()
