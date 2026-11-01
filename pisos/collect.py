"""Descarga CRUDA diaria de Fotocasa. Solo añade data/pisos/raw/<run_id>_search.csv."""
import csv, json, re, sys, time, argparse, glob, hashlib
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


DROP = {"multimedia", "detail", "detailWithParams", "brandInfo", "promotionLogo", "date", "isFaved", "isContacted",
        "isDiscarded", "isVisited", "isTop", "isSuperTop", "isTopPlus", "isHighlighted", "isPremium", "isNew", "phone",
        "hasListLogo", "isPackAdvancePriority", "isPackBasicPriority", "isPackMinimalPriority", "isPackPremiumPriority",
        "isPrioritaryAndMultimediaRule", "hasPhoneVisibility", "isTrackedPhone", "isMsAdvance"}
ITEMS = ROOT / "data" / "pisos" / "raw" / "items.jsonl"


def stripped(it):
    d = {k: v for k, v in it.items() if k not in DROP}
    d["n_photos"] = len(it.get("multimedia") or [])
    return d


def save_items(items, run_id, now):
    """Guarda el anuncio COMPLETO la primera vez que se ve y cada vez que cambia algo (no repite lo igual)."""
    last = {}
    if ITEMS.exists():
        for line in open(ITEMS, encoding="utf-8"):
            o = json.loads(line); last[o["id"]] = o["h"]
    new = 0
    with open(ITEMS, "a", encoding="utf-8") as fh:
        for it in items:
            d = stripped(it)
            h = hashlib.md5(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]
            if last.get(it["id"]) != h:
                fh.write(json.dumps({"id": it["id"], "run_id": run_id, "seen_at": now, "h": h, "item": d}, ensure_ascii=False) + "\n")
                last[it["id"]] = h; new += 1
    print(f"items.jsonl: {new} anuncios nuevos o cambiados")


def detail(client, url_):
    """Consulta la ficha. Devuelve (existe, datos). Redirección a ?propertyNotFound = retirado."""
    for i in range(3):
        try:
            r = client.get(url_, follow_redirects=False)
            if r.status_code in (301, 302, 303, 307, 308):
                return (0 if "propertyNotFound" in r.headers.get("location", "") else None), {}
            m = PROPS.search(r.text) if r.status_code == 200 else None
            if m:
                e = json.loads(m.group(1))["realEstateAdDetailEntityV2"]
                ec = e.get("energyCertificate") or {}
                return 1, {"price_now": (e.get("price") or {}).get("amount"), "energy": ec.get("energyEfficiencyRatingType"),
                           "energy_kwh": ec.get("energyEfficiency"), "co2": ec.get("environmentImpactRatingType"),
                           "construction": e.get("constructionType"), "ground_surface": e.get("groundSurface"),
                           "features": json.dumps(e.get("features"), ensure_ascii=False)}
            if r.status_code == 404:
                return 0, {}
        except Exception as ex:
            print("  error", ex)
        time.sleep(3 * (i + 1))
    return None, {}


def read_raw():
    seen, removed, detailed = {}, set(), set()
    for f in sorted(glob.glob(str(ROOT / "data/pisos/raw/*_search*.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            seen[r["id"]] = (r["run_id"], r["url"])
    for f in sorted(glob.glob(str(ROOT / "data/pisos/raw/*_status.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if r["exists"] == "0":
                removed.add(r["id"])
    for f in sorted(glob.glob(str(ROOT / "data/pisos/raw/*_details.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            detailed.add(r["id"])
    return seen, removed, detailed


STATUS_COLS = ["run_id", "checked_at", "id", "exists", "price_now"]
DETAIL_COLS = ["run_id", "checked_at", "id", "energy", "energy_kwh", "co2", "construction", "ground_surface", "features"]


def write(path, cols, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only"); ap.add_argument("--run-id")
    a = ap.parse_args()
    run_id = a.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg = yaml.safe_load(open(Path(__file__).with_name("pisos.yml"), encoding="utf-8"))["searches"]
    rows, ok, allitems = [], True, []
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
                        seen.add(i["id"]); rows.append(row(i, run_id, s["id"], zone, now)); allitems.append(i)
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
    out.mkdir(parents=True, exist_ok=True)
    save_items(list({i["id"]: i for i in allitems}.values()), run_id, now)
    if not ok:
        return
    seen_all, removed, detailed = read_raw()
    now_ids = {str(r["id"]) for r in rows}
    with httpx.Client(headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"}, timeout=40) as c:
        # 1) los que ya no salen: ¿siguen existiendo? (retirado = vendido o retirado; fuera de filtro = sigue con otro precio)
        gone = [(i, u) for i, (rid, u) in seen_all.items() if i not in now_ids and i not in removed][:300]
        st = []
        for i, u in gone:
            ex, d = detail(c, u)
            st.append({"run_id": run_id, "checked_at": now, "id": i, "exists": "" if ex is None else ex, "price_now": d.get("price_now")})
            time.sleep(1)
        write(out / f"{run_id}_status.csv", STATUS_COLS, st)
        # 2) ficha completa (certificado energético, etc.) una vez por anuncio nuevo, máx. 300 por ejecución
        todo = [(str(r["id"]), r["url"]) for r in rows if str(r["id"]) not in detailed][:300]
        ds = []
        for i, u in todo:
            ex, d = detail(c, u)
            if ex:
                ds.append({"run_id": run_id, "checked_at": now, "id": i, **d})
            time.sleep(1)
        write(out / f"{run_id}_details.csv", DETAIL_COLS, ds)
        print(f"status: {len(st)} comprobados ({sum(1 for x in st if x['exists'] == 0)} retirados); fichas: {len(ds)}")


if __name__ == "__main__":
    main()