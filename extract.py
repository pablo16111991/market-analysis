#!/usr/bin/env python3
"""Extracción por reglas de marca, modelo, variante, ABS, año, km y señales de descarte.

Cada campo lleva su fuente: 'estructurado' (atributos de Wallapop), 'titulo', 'descripcion'
o vacío. Lo que no se puede saber se deja a None (nunca se inventa). El LLM solo debería
mirar las filas con huecos o contradicciones.

Lo usa clean.py (función features).
"""
import argparse
import csv
import json
import re
from datetime import datetime

THIS_YEAR = datetime.now().year

# marca canónica -> patrón (sobre texto en minúsculas)
BRANDS = {
    "Honda": r"honda", "Yamaha": r"yamaha", "Kymco": r"kymco", "Suzuki": r"suzuki",
    "Kawasaki": r"kawasaki", "Piaggio": r"piaggio", "Vespa": r"vespa", "Peugeot": r"peugeot",
    "SYM": r"sym", "Daelim": r"daelim", "Aprilia": r"aprilia", "Derbi": r"derbi",
    "Gilera": r"gilera", "Beta": r"beta", "Sherco": r"sherco", "GasGas": r"gas\s?gas",
    "KTM": r"ktm", "BMW": r"bmw", "Ducati": r"ducati", "Triumph": r"triumph",
    "Harley-Davidson": r"harley(?:[\s-]?davidson)?", "Royal Enfield": r"royal\s?enfield",
    "Benelli": r"benelli", "Keeway": r"keeway", "Rieju": r"rieju", "Mash": r"mash",
    "Zontes": r"zontes", "CFMoto": r"cf\s?moto", "Voge": r"voge", "Husqvarna": r"husqvarna",
    "Montesa": r"montesa", "Bultaco": r"bultaco", "Lambretta": r"lambretta",
    "Italjet": r"italjet", "Malaguti": r"malaguti", "MBK": r"mbk", "Hyosung": r"hyosung",
    "SWM": r"swm", "Fantic": r"fantic", "Macbor": r"macbor", "Orcal": r"orcal",
    "Brixton": r"brixton", "Silence": r"silence", "Super Soco": r"super\s?soco",
    "Horwin": r"horwin", "NIU": r"niu", "QJ Motor": r"qj\s?motor", "Lifan": r"lifan",
    "Bajaj": r"bajaj", "Mondial": r"mondial", "Moto Guzzi": r"moto\s?guzzi",
    "MV Agusta": r"mv\s?agusta", "Indian": r"indian", "Can-Am": r"can[\s-]?am",
    "Torrot": r"torrot", "Vmoto": r"vmoto", "Zero": r"zero\b(?=\s?(?:motorcycles|s|sr|ds|fx))",
}
BRAND_RES = [(b, re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % p)) for b, p in BRANDS.items()]

# Variantes por marca/modelo conocidas (se amplía según haga falta)
VARIANT_RES = [
    ("K-XCT 125i", re.compile(r"k-?\s?xct\s*125\s*i\b|kxct\s*125\s*i\b")),
    ("K-XCT 125", re.compile(r"k-?\s?xct\s*125|kxct\s*125|k-?\s?xct(?!\s*(?:200|300))")),
    ("K-XCT 200i", re.compile(r"k-?\s?xct\s*200|kxct\s*200")),
    ("K-XCT 300i", re.compile(r"k-?\s?xct\s*300|kxct\s*300")),
    ("Trident 660", re.compile(r"trident\s*(?:660)?(?!\s*(?:7|1)\d\d)")),
]

STOP = {
    "de", "del", "en", "con", "para", "por", "y", "a", "el", "la", "los", "las", "un", "una",
    "moto", "motos", "scooter", "motocicleta", "cc", "km", "kms", "año", "ano", "negro", "negra",
    "blanco", "blanca", "gris", "rojo", "roja", "azul", "verde", "amarillo", "naranja", "plata",
    "se", "vende", "vendo", "muy", "buen", "buena", "estado", "perfecto", "perfecta", "impecable",
    "nueva", "nuevo", "oferta", "urgente", "ocasion", "ocasión", "revisada", "itv", "papeles",
    "a2", "carnet", "carné", "b", "permiso",
}

FLAG_PATTERNS = {
    "piezas": r"para\s+piezas|solo\s+piezas|despiece|desguace|recambios?\b",
    "averiada": r"aver[ií]ad|no\s+arranca|no\s+funciona|para\s+reparar|siniestro|accidentad|golpe\s+fuerte",
    "sin_papeles": r"sin\s+papeles|sin\s+documentaci[oó]n|sin\s+matr[ií]cula|baja\s+definitiva|ficha\s+t[eé]cnica\s+sola",
    "busca": r"\bse\s+busca\b|\bcompro\b|\bbusco\b",
    "permuta": r"parte\s+de\s+pago|\bpermuta|acept\w+\s+cambios|escucho\s+cambios|admito\s+cambios",
    "posible_nueva": r"\bnuev[ao]s?\b|a\s+estrenar|0\s?km\b",
}
FLAG_RES = {k: re.compile(v) for k, v in FLAG_PATTERNS.items()}

A2_POS = re.compile(r"\ba2\b|limitad[ao]|35\s?kw|47[,.]?\d?\s?cv")
A2_NEG = re.compile(r"sin\s+limit\w+|no\s+(?:est[aá]\s+)?limitad[ao]|full\s+power|libre\s+de\s+limit\w+|potencia\s+completa")
QS_POS = re.compile(r"quick\s?-?shift\w*|cambio\s+r[aá]pido")
QS_NEG = re.compile(r"sin\s+quick\s?-?shift\w*")
# Señales de que vende una tienda/concesionario y no un particular
SHOP_RE = re.compile(r"financiaci[oó]n|parte de pago|nuestras tiendas|empresa\b|c[uü]imo|motick|maquina motors|"
                     r"env[ií]o\s+(?:gratuito\s+|gratis\s+|a domicilio\s+)?a\s+toda\s+(?:la\s+pen[ií]nsula|espa[ñn]a)|"
                     r"moto\s+ocasi[oó]n|iva\s+(?:incluido|deducible)|aceptamos\s+tu\s+moto|carece de valor contractual")
ABS_NEG = re.compile(r"\b(sin|no\s+tiene|no\s+lleva|carece\s+de|sin\s+el)\s+abs\b")
ABS_POS = re.compile(r"\babs\b")
YEAR_RE = re.compile(r"(?<!\d)(19[89]\d|20[0-2]\d)(?!\d)")
YEAR_CUE = re.compile(r"(?:\bdel|año|ano|matriculad[ao]|matriculaci[oó]n|modelo|primera)\s+(?:de\s+)?(19[89]\d|20[0-2]\d)(?!\d)")
KM_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+|\d{3,6})\s?(?:km|kms|kil[oó]metros)\b(?!\s?/?\s?h\b)")
KM_BAD_CTX = re.compile(r"(cada|revis\w*|aceite|correa|hasta|cambio|menos de|autonom[ií]a|velocidad)\s*(de\s*)?$")
CC_RE = re.compile(r"(?<!\d)(\d{2,4})\s?cc\b")
MODEL_NUM_RE = re.compile(r"(?<!\d)(\d{2,4})(?!\d)")
CC_VALID = {50, 70, 80, 100, 110, 125, 150, 160, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 660, 700,
            750, 800, 900, 1000, 1100, 1200, 1250}
VARIANT_CC = {"K-XCT 125": 125, "K-XCT 125i": 125, "K-XCT 200i": 200, "K-XCT 300i": 300, "Trident 660": 660}


def find_cc(variant, model, title, desc):
    """Cilindrada: variante conocida > número del modelo > 'NNN cc' del título > descripción (solo si no hay ambigüedad)."""
    if variant in VARIANT_CC:
        return VARIANT_CC[variant], "variante"
    for n in MODEL_NUM_RE.findall(model or ""):
        if int(n) in CC_VALID:
            return int(n), "modelo"
    m = CC_RE.search(norm(title))
    if m and int(m.group(1)) in CC_VALID:
        return int(m.group(1)), "titulo"
    nums = {int(n) for n in MODEL_NUM_RE.findall(title or "") if int(n) in CC_VALID and int(n) <= 650}
    if len(nums) == 1:  # un único número tipo cilindrada en el título (≤650 para no confundir con km)
        return nums.pop(), "titulo (número)"
    vals = {int(x) for x in CC_RE.findall(norm(desc)) if int(x) in CC_VALID}
    if len(vals) == 1:  # la descripción de un concesionario cita varias motos: si hay más de un cc, no fiarse
        return vals.pop(), "descripcion"
    return None, None


def norm(s):
    return (s or "").lower()


def find_brand(text):
    t = norm(text)
    for brand, rx in BRAND_RES:
        if rx.search(t):
            return brand
    return None


def find_variant(text):
    t = norm(text)
    for name, rx in VARIANT_RES:
        if rx.search(t):
            return name
    return None


def guess_model(title, brand):
    """Modelo estimado: hasta 3 tokens tras la marca en el título (fuente débil)."""
    t = re.sub(r"[,;:()|/]", " ", title or "")
    toks = t.split()
    low = [x.lower() for x in toks]
    rx = dict(BRAND_RES).get(brand)
    start = None
    if rx:
        for i, w in enumerate(low):
            if rx.fullmatch(w) or (i + 1 < len(low) and rx.fullmatch(f"{w} {low[i+1]}")):
                start = i + (2 if " " in (brand or "") and rx.fullmatch(f"{w} {low[i+1]}") else 1)
                break
    if start is None:
        return None
    out = []
    for w, l in zip(toks[start:], low[start:]):
        if l in STOP or YEAR_RE.fullmatch(l) or re.fullmatch(r"\d{1,3}[.,]\d{3}", l):
            if out:
                break
            continue
        out.append(w)
        if len(out) == 3:
            break
    return " ".join(out) or None


def find_year(title, desc):
    m = YEAR_RE.search(title or "")
    if m and int(m.group(1)) <= THIS_YEAR:
        return int(m.group(1)), "titulo"
    m = YEAR_CUE.search(norm(desc))
    if m and int(m.group(1)) <= THIS_YEAR:
        return int(m.group(1)), "descripcion"
    return None, None


def find_km(title, desc):
    for text, src in ((title, "titulo"), (desc, "descripcion")):
        t = norm(text)
        for m in KM_RE.finditer(t):
            before = t[max(0, m.start() - 14):m.start()]
            if KM_BAD_CTX.search(before):  # "revisiones cada 5000 km" no es el kilometraje
                continue
            v = int(re.sub(r"[.,]", "", m.group(1)))
            if 500 <= v <= 400000:
                return v, src
    return None, None


def find_abs(title, desc):
    t = norm(f"{title} {desc}")
    if ABS_NEG.search(t):
        return False
    if ABS_POS.search(t):
        return True
    return None


def features(row):
    """row: dict con title, description, y opcionalmente attrs (dict de atributos estructurados)."""
    title, desc = row.get("title") or "", row.get("description") or ""
    attrs = row.get("attrs") or {}
    text = f"{title} {desc}"
    out = {}

    b = attrs.get("brand")
    if b:
        out["brand"], out["brand_src"] = find_brand(b) or b, "estructurado"
    else:
        bt = find_brand(title)
        if bt:
            out["brand"], out["brand_src"] = bt, "titulo"
        else:
            bd = find_brand(desc)
            out["brand"], out["brand_src"] = (bd, "descripcion") if bd else (None, None)

    m = attrs.get("model")
    if m:
        out["model"], out["model_src"] = m, "estructurado"
    else:
        g = guess_model(title, out["brand"])
        out["model"], out["model_src"] = (g, "titulo (estimado)") if g else (None, None)

    # La descripción no vale: los concesionarios meten "Kymco K-XCT 125" para colarse en búsquedas.
    out["variant"] = find_variant(f"{m or ''} {title}") if out["brand"] in (None, "Kymco", "Triumph") else None
    out["cc"], out["cc_src"] = find_cc(out["variant"], out["model"], title, desc)

    y = attrs.get("year")
    if y not in (None, ""):
        out["year"], out["year_src"] = int(float(y)), "estructurado"
    else:
        out["year"], out["year_src"] = find_year(title, desc)

    k = attrs.get("km")
    if k not in (None, ""):
        out["km"], out["km_src"] = int(float(str(k).replace(".", "").replace(",", ""))), "estructurado"
    else:
        out["km"], out["km_src"] = find_km(title, desc)

    out["abs"] = find_abs(title, desc)
    tl = norm(text)
    out["a2"] = 0 if A2_NEG.search(tl) else (1 if A2_POS.search(tl) else None)  # 1 = limitada/apta A2, 0 = libre
    out["quickshifter"] = 0 if QS_NEG.search(tl) else (1 if QS_POS.search(tl) else None)
    t = norm(text)
    tt = norm(title)  # "nueva" solo cuenta en el título ("ruedas nuevas" no es una moto nueva)
    flags = [k for k, rx in FLAG_RES.items() if rx.search(tt if k == "posible_nueva" else t)]
    tcc = CC_RE.search(tt)
    if tcc and out["cc"] and int(tcc.group(1)) in CC_VALID and int(tcc.group(1)) != out["cc"]:
        flags.append("cc_discrepancia")  # el título dice otro cc que el modelo
    out["shop_signals"] = len(SHOP_RE.findall(t))
    out["flags"] = ",".join(flags)
    return out
