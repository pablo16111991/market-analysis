"""Reconstruye data/clean/<search>.csv (1 fila por anuncio, último estado) desde TODO lo crudo."""
import csv, glob, json, re, sys
from collections import defaultdict
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent
COLS = ["id", "url", "state", "in_scope", "price_first", "price_last", "price_changes", "drop_pct", "reduced_price",
        "eur_m2", "rooms", "bathrooms", "surface", "floor", "subtype", "exterior", "antiquity", "conservation",
        "orientation", "energy", "energy_kwh", "co2", "construction", "ground_surface", "locality", "neighborhood", "municipality", "zone", "lat", "lon", "client_type", "client_alias",
        "occupied", "bare_ownership", "auctioned", "rented", "new_construction", "okupa_txt", "nuda_txt", "a_reformar", "publication_date", "first_seen",
        "last_seen", "days_listed", "runs_seen", "dup_n", "desc_start"]


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


def in_scope(r, sc):
    # Siempre fuera: ocupado/okupa, nuda propiedad/usufructo y subasta (por bandera de Fotocasa o por texto).
    # Los alquilados con inquilinos (rented) SÍ entran: se reportan con su columna.
    if r["occupied"] == "1" or r["bare_ownership"] == "1" or r["auctioned"] == "1" or r["okupa_txt"] or r["nuda_txt"]:
        return 0
    sc = sc or {}
    ex = {n.lower() for n in sc.get("exclude_neighborhoods", [])}
    if ex and ((r["neighborhood"] or "").lower() in ex or (r["locality"] + "/" + (r["neighborhood"] or "")).lower() in ex):
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
        sur = num(d["surface"])
        d.update({
            "state": "activo" if seen_last else ("retirado" if iid in removed else ("fuera_de_filtro" if iid in now_price else "desaparecido")),
            "price_first": prices[0], "price_last": prices[-1], "price_changes": changes,
            "drop_pct": round(100 * (prices[-1] - prices[0]) / prices[0], 1) if prices[0] else None,
            "eur_m2": round(prices[-1] / sur) if sur else None,
            "first_seen": first["seen_at"][:10], "last_seen": last["seen_at"][:10], "runs_seen": len({r["run_id"] for r in rs}),
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
        d["in_scope"] = in_scope(d, scope)
        recs.append(d)
    key = lambda r: (r["price_last"], r["surface"], r["rooms"], r["neighborhood"], r["client_alias"])
    from collections import Counter
    cnt = Counter(key(r) for r in recs)
    for r in recs:
        r["dup_n"] = cnt[key(r)]
    # Duplicados: de cada grupo solo entra en ámbito el de id más bajo (los demás, in_scope=0)
    keep = {}
    for r in sorted(recs, key=lambda r: int(r["id"])):
        if r["in_scope"] and key(r) not in keep:
            keep[key(r)] = r["id"]
    for r in recs:
        if r["in_scope"] and keep[key(r)] != r["id"]:
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
