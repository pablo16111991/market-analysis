"""Lectura/escritura de lo crudo de pisos. Los ficheros nuevos van comprimidos (.gz) porque GitHub no acepta
ficheros de más de 100 MB y el repo crece cada día:
- anuncios completos: data/raw/items/<run>.jsonl.gz (uno por ejecución, solo nuevos o cambiados). El antiguo
  data/raw/items.jsonl (hasta 2026-11-13) se sigue leyendo, pero ya no se escribe.
- foto diaria: data/raw/<run>_search.csv.gz (antes <run>_search.csv, que se siguen leyendo).
"""
import glob, gzip, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
LEGACY_ITEMS = RAW / "items.jsonl"
ITEMS_DIR = RAW / "items"


def open_text(path):
    path = str(path)
    return gzip.open(path, "rt", encoding="utf-8") if path.endswith(".gz") else open(path, encoding="utf-8")


def item_files():
    files = [LEGACY_ITEMS] if LEGACY_ITEMS.exists() else []
    return files + [Path(p) for p in sorted(glob.glob(str(ITEMS_DIR / "*.jsonl.gz")))]


def iter_items():
    """Registros {id, run_id, seen_at, h, item} en orden cronológico (el último de cada id es el vigente)."""
    for f in item_files():
        with open_text(f) as fh:
            for line in fh:
                yield json.loads(line)


def search_files(complete_only=False):
    """Fotos diarias (csv antiguos y csv.gz nuevos), ordenadas por run_id."""
    pat = ["*_search.csv", "*_search.csv.gz"] if complete_only else ["*_search*.csv", "*_search*.csv.gz"]
    files = {p for g in pat for p in glob.glob(str(RAW / g))}
    return sorted(files, key=lambda p: Path(p).name)
