#!/usr/bin/env bash
# Uso: ./run.sh <carpeta> "<busqueda>" <categoria> <precio_min>
set -e
D="$1"; Q="$2"; CAT="$3"; MIN="$4"
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/$D"
python3 ../scrape.py "$Q" --category "$CAT" --min-price "$MIN" --max-pages 12 --db wallapop.db
python3 ../scrape.py --details --limit 200 --db wallapop.db || true
python3 ../scrape.py --check-gone --limit 200 --db wallapop.db || true
python3 ../extract.py --db wallapop.db --csv base_de_datos.csv
