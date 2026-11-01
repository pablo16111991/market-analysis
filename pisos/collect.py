"""Descarga CRUDA diaria de Fotocasa. Solo añade data/pisos/raw/<run_id>_search.csv."""
import csv, json, re, sys, time, argparse
from datetime import datetime, timezone
from pathlib import Path
import httpx, yaml

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
COLS = ["run_id", "search", "zone", "seen_at", "id", "url", "price", "reduced_price", "rooms", "bathrooms", "surface",
        "floor", "antiquity", "conservation", "orientation", "exterior", "subtype", "locality", "neighborhood",
        "municipality", "lat", "lon", "publication_date", "client_type", "client_alias", "occupied", "bare_ownership",
        "auctioned", "rented", "new_construction", "desc_start"]
PROPS = re.compile(r'<script type="application/json" id="__initial_props__">(.*?)</script>', re.S)


def url(zone, page, s):
    q = f"?minPrice={s['min_price']}&maxPrice={s['max_price']}&minRooms={s.get('min_rooms', 0)}"
    return f"https://www.fotocasa.es/es/comprar/viviendas/{zone}/todas-las-zonas/l{'/%d' % page if page > 1 else ''}{q}"


def fetch(client, u):
    for i in range(3):
        try:
            r = client.get(u)
            m = PROPS.search(r.text) if r.status_code == 200 else None
            if m:
                return json.loads(m.group(1))["initialSearch"]["result"]
        except Exception as e:
            print("  error", e)
        time.sleep(3 * (i + 1))
    return None


def row(it, run_id, sid, zone, now):
    ft = {f["key"]: f["value"] for f in it.get("features", [])}
    a = it["address"]
    return {
        "run_id": run_id, "search": sid, "zone": zone, "seen_at": now, "id": it["id"],
        "url": "https://www.fotocasa.es" + it["detailUrl"], "price": it["rawPrice"], "reduced_price": it.get("reducedPrice"),
        "rooms": ft.get("rooms"), "bathrooms": ft.get("bathrooms"), "surface": ft.get("surface"), "floor": ft.get("floor"),
        "antiquity": ft.get("antiquity"), "conservation": ft.get("conservationStatus"), "orientation": ft.get("orientation"),
        "exterior": int("IS_EXTERIOR" in it.get("dynamicFeatures", [])), "subtype": it.get("propertySubtype"),
        "locality": a.get("locality"), "neighborhood": a.get("neighborhood"), "municipality": a.get("municipality"),
        "lat": (a.get("coordinates") or {}).get("lat"), "lon": (a.get("coordinates") or {}).get("lng"),
        "publication_date": (it.get("publicationDate") or "")[:10], "client_type": it.get("clientType"),
        "client_alias": it.get("clientAlias"), "occupied": int(bool(it.get("isOccupied"))),
        "bare_ownership": int(bool(it.get("isBareOwnership"))), "auctioned": int(bool(it.get("isAuctioned"))),
        "rented": int(bool(it.get("isRentedWithTenants"))), "new_construction": int(bool(it.get("isNewConstruction"))),
        "desc_start": (it.get("description") or "").replace("\n", " ")[:140],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only"); ap.add_argument("--run-id")
    a = ap.parse_args()
    run_id = a.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg = yaml.safe_load(open(Path(__file__).with_name("pisos.yml"), encoding="utf-8"))["searches"]
    rows, ok = [], True
    with httpx.Client(headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"}, timeout=40, follow_redirects=True) as c:
        for s in cfg:
            if a.only and s["id"] != a.only:
                continue
            for zone in s["zones"]:
                seen, got, total = set(), 0, None
                for page in range(1, 200):
                    r = fetch(c, url(zone, page, s))
                    if not r:
                        print(f"[{s['id']}/{zone}] fallo en página {page}"); ok = False; break
                    total = r.get("count", total)
                    items = r["resultsV2"]["items"]
                    new = [i for i in items if i["id"] not in seen]
                    if not new:
                        break
                    for i in new:
                        seen.add(i["id"]); rows.append(row(i, run_id, s["id"], zone, now))
                    if len(seen) >= total:
                        break
                    time.sleep(1)
                print(f"[{s['id']}/{zone}] {len(seen)} de {total}")
                if total and len(seen) < total * 0.95:
                    print("  AVISO: incompleto"); ok = False
    if not rows:
        sys.exit("sin datos")
    out = ROOT / "data" / "pisos" / "raw"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{run_id}_search{'' if ok else '_INCOMPLETO'}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} filas, run {run_id}, completo={ok}")


if __name__ == "__main__":
    main()
