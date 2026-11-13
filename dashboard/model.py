"""Modelo de precio de pisos (regresion ridge sobre log(precio)) en numpy puro.

Idea: el precio "justo" de un piso = lo que piden por pisos parecidos (mismo barrio, m2, planta, estado...).
El descuento de un anuncio = su precio / precio justo - 1 (negativo = mas barato que el mercado).
Para no premiar al propio anuncio, el precio justo de cada anuncio es "fuera de muestra" (validacion cruzada).

Zona: efecto de barrio + efecto de ciudad (186 municipios a <= 60 min de Pl. Catalunya) + un gradiente por
minutos en coche a BCN, para que las ciudades con pocos anuncios no queden en la media general.
Limites: aprende solo del rango que se descarga (150-350k), usa lo que piden (no lo que se paga) y
no ve fotos ni calle exacta. Corrige el sesgo de ver solo ese rango con una regresion normal truncada.
"""
import json
import math

import numpy as np
import pandas as pd

FLOORS = {"GROUND_FLOOR": 0, "MEZZANINE": 0.5, "1ST_FLOOR": 1, "2ND_FLOOR": 2, "3RD_FLOOR": 3, "4TH_FLOOR": 4,
          "5TH_FLOOR": 5, "6TH_FLOOR": 6, "7TH_FLOOR": 7, "8TH_FLOOR": 8, "PENTHOUSE": 9}
BIN_FLAGS = ["terraza", "balcon", "patio_jardin", "trastero", "aire", "piscina", "luminoso", "reformado",
             "vista_mar", "parking", "amueblado"]
CONS = ["ALMOST_NEW", "REFURBISHED", "VERY_GOOD", "FOR_RENOVATION"]
ANTI = ["LESS_THAN_1_YEAR", "BETWEEN_1_AND_5_YEARS", "BETWEEN_10_AND_20_YEARS", "BETWEEN_20_AND_30_YEARS",
        "BETWEEN_30_AND_50_YEARS", "BETWEEN_70_AND_100_YEARS", "MORE_THAN_100_YEARS"]
SUBT = ["PENTHOUSE", "GROUND_FLOOR", "DUPLEX_APARTMENT", "LOFT", "STUDIO", "APARTMENT"]
CELL_LAT, CELL_LON = 0.005, 0.007   # ~500 m


def barrio_key(neigh, mun):
    return f"{neigh}|{mun}"


def area_label(district, city):
    """Zona de Fotocasa (distrito) con su ciudad, porque hay distritos con el mismo nombre en varias ciudades."""
    district = "" if pd.isna(district) else str(district).strip()
    if city == "Barcelona" and district:
        return district
    return f"{district} · {city}" if district and district != city else city


def design(d):
    """d: DataFrame con columnas limpias + 'f' (lista de etiquetas) + features de detalle (FLOOR, ...)."""
    X = {}
    X["lsurf"] = np.log(d.surface)
    X["rooms"] = d.rooms.fillna(d.rooms.median())
    X["baths"] = d.bathrooms.fillna(1)
    fl = d.FLOOR.map(FLOORS)
    X["floor_known"] = fl.notna().astype(float)
    fl = fl.fillna(2)
    elev = d.f.apply(lambda f: "ascensor" in f).astype(float)
    X["elev"] = elev
    X["floor"] = fl.clip(upper=7)
    X["walkup_high"] = ((1 - elev) * (fl >= 3)).astype(float)
    X["ext"] = (d.exterior == 1).astype(float)
    for k in BIN_FLAGS:
        X["f_" + k] = d.f.apply(lambda f, k=k: k in f).astype(float)
    X["rented"] = (d.rented == 1).astype(float)
    X["a_reformar"] = (d.a_reformar == 1).astype(float)
    X["particular"] = (d.client_type == "particular").astype(float)
    for k in CONS:
        X["c_" + k] = (d.CONSERVATION_STATE == k).astype(float)
    X["c_unk"] = d.CONSERVATION_STATE.isna().astype(float)
    ant = d.ANTIQUITY.fillna("?")
    for k in ANTI:
        X["a_" + k] = (ant == k).astype(float)
    for k in SUBT:
        X["s_" + k] = (d.subtype == k).astype(float)
    X["e_G"] = (d.energy == "G").astype(float)
    X["e_good"] = d.energy.isin(["A", "B", "C", "D"]).astype(float)
    X["min_bcn"] = d.min_bcn.fillna(d.min_bcn.median()) / 10   # por cada 10 min en coche
    X = pd.DataFrame(X, index=d.index)
    B = pd.get_dummies(d.bkey, prefix="b").astype(float)
    T = pd.get_dummies(d.city, prefix="t").astype(float)
    cell = (np.floor(d.lat / CELL_LAT).astype("Int64").astype(str) + "_" + np.floor(d.lon / CELL_LON).astype("Int64").astype(str))
    C = pd.get_dummies(cell, prefix="g").astype(float)
    C = C.loc[:, C.sum() >= 4]
    return X, B, T, C


_erf = np.vectorize(math.erf)


def _Phi(z):
    return 0.5 * (1 + _erf(z / math.sqrt(2)))


def _phi(z):
    return np.exp(-z * z / 2) / math.sqrt(2 * math.pi)


def _lam(m, s, lo, hi):
    """E[(y-m)/s | lo<=y<=hi] para y~N(m,s): corrige que solo vemos pisos dentro del rango descargado."""
    a, b = (lo - m) / s, (hi - m) / s
    return (_phi(a) - _phi(b)) / np.maximum(_Phi(b) - _Phi(a), 1e-9)


C_SIZE = 0.85   # el precio sube ~ con m2^0.85 (a priori); el modelo ajusta la desviacion


def _trunc_fit(M, y, ls, Ainv, s, lo, hi, iters=60):
    """Regresion normal truncada con ridge (iteracion de punto fijo). y y limites en log(precio).
    Ainv = (M'M + diag(pen))^-1, calculada una vez fuera (es lo caro con miles de columnas)."""
    yy, lo_i, hi_i = y - C_SIZE * ls, lo - C_SIZE * ls, hi - C_SIZE * ls
    w = Ainv @ (M.T @ yy)
    for _ in range(iters):
        mu = M @ w
        w2 = Ainv @ (M.T @ (yy - s * _lam(mu, s, lo_i, hi_i)))
        done = np.max(np.abs(w2 - w)) < 1e-6
        w = w2
        if done:
            break
    mu = M @ w
    a, b = (lo_i - mu) / s, (hi_i - mu) / s
    ll = float(np.sum(-0.5 * ((yy - mu) / s) ** 2 - np.log(s) - np.log(np.maximum(_Phi(b) - _Phi(a), 1e-12))))
    return w, ll


def fit(d, lam_x=0.5, lam_b=2.0, lam_t=1.0, lam_c=5.0, lam_size=0.05, folds=10, seed=0):
    """Devuelve (modelo, precio de mercado sin truncar, precio tipico de pisos parecidos que SE VEN en el rango); ambos fuera de muestra."""
    X, B, T, C = design(d)
    y = np.log(d.price_last.values)
    ls = np.log(d.surface.values)
    lo, hi = float(np.log(d.price_last.min())), float(np.log(d.price_last.max()))
    M = pd.concat([X, B, T, C], axis=1)
    mu = M.mean()
    Mc = np.hstack([np.ones((len(M), 1)), (M - mu).values])
    pen = np.array([0.0] + [lam_x] * X.shape[1] + [lam_b] * B.shape[1] + [lam_t] * T.shape[1] + [lam_c] * C.shape[1])
    pen[1 + list(X.columns).index("lsurf")] = lam_size   # lsurf: desviacion respecto a C_SIZE
    G = Mc.T @ Mc
    Ainv = np.linalg.inv(G + np.diag(pen))

    # sigma (desviacion tipica del log-precio dado todo lo demas) por maxima verosimilitud en una rejilla
    best = None
    for s in [0.10, 0.12, 0.14, 0.16, 0.18, 0.22]:
        w, ll = _trunc_fit(Mc, y, ls, Ainv, s, lo, hi)
        if best is None or ll > best[0]:
            best = (ll, s)
    sigma = best[1]

    idx = np.random.RandomState(seed).permutation(len(d))
    fair = np.zeros(len(d))   # log precio justo (media sin truncar)
    pred = np.zeros(len(d))   # esperanza condicionada al rango, para medir el error contra lo observado
    for f in np.array_split(idx, folds):
        tr = np.setdiff1d(idx, f)
        Mf = Mc[f]
        w, _ = _trunc_fit(Mc[tr], y[tr], ls[tr], np.linalg.inv(G - Mf.T @ Mf + np.diag(pen)), sigma, lo, hi)
        m = Mc[f] @ w
        fair[f] = m + C_SIZE * ls[f]
        pred[f] = fair[f] + sigma * _lam(m, sigma, lo - C_SIZE * ls[f], hi - C_SIZE * ls[f])
    err = np.exp(pred) / d.price_last.values - 1

    w, _ = _trunc_fit(Mc, y, ls, Ainv, sigma, lo, hi)
    const, coefs = w[0], pd.Series(w[1:], index=M.columns)
    base = float(const - (coefs[X.columns] * mu[X.columns]).sum())
    sum_b = float((coefs[B.columns] * mu[B.columns]).sum())   # celdas: se anulan al fijarlas en su media
    sum_t = float((coefs[T.columns] * mu[T.columns]).sum())
    coef_x = {c: float(coefs[c]) for c in X.columns}
    coef_x["lsurf"] += C_SIZE
    # La ciudad y sus minutos a BCN se suman al efecto de cada barrio: el valorador solo pide el barrio.
    c_min = coef_x.pop("min_bcn")
    city = d.groupby("bkey").city.first()
    mins = d.groupby("bkey").min_bcn.first().fillna(d.min_bcn.median()) / 10
    barrio = {c[2:]: float(coefs[c] - sum_b + coefs["t_" + city[c[2:]]] - sum_t + c_min * mins[c[2:]]) for c in B.columns}
    model = {"k": base, "x": coef_x, "barrio": barrio, "min_bcn_10": c_min,
             "n_barrio": {k: int(v) for k, v in d.bkey.value_counts().items()},
             "sigma": float(sigma), "lo": float(np.exp(lo)), "hi": float(np.exp(hi)),
             "med_pct": float(np.median(np.abs(err))), "mae_pct": float(np.mean(np.abs(err))), "n": int(len(d))}
    return model, pd.Series(np.exp(fair), index=d.index), pd.Series(np.exp(pred), index=d.index)


def load_details(ids, files):
    det = {}
    for f in files:
        for r in pd.read_csv(f, usecols=["id", "features"]).itertuples():
            if r.id in ids and isinstance(r.features, str):
                det[r.id] = {x["type"]: x["value"] for x in json.loads(r.features)}
    return det
