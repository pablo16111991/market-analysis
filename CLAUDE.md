# wallapop-analysis

Analizador de precios de Wallapop de Pablo (sin servicios de pago). Responde en español, corto y directo.

## Estructura
- `products.yml`: productos a seguir (id, query, category, min_price, max_price, max_pages, lat/lon).
- `collect.py`: descarga CRUDA diaria (solo añade ficheros) en `data/raw/<run_id>_{search,details,status}.csv` (todos los productos juntos, columna `product`).
- `clean.py`: reconstruye `data/clean/<id>.csv` (1 fila por anuncio, último estado) desde lo crudo.
- `extract.py`: reglas para marca, modelo, variante, cc, año, km, ABS y flags. `VARIANT_RES` y `VARIANT_CC` están ajustados a Kymco K-XCT: para otro modelo hay que añadir sus variantes.
- `.github/workflows/scrape.yml`: Actions diario (collect + clean + commit). Lanzar a mano: `gh api -X POST repos/pablo16111991/wallapop-analysis/actions/workflows/scrape.yml/dispatches -f ref=main`.

## Estados en clean.csv
activo, reservado, vendido, caducado, borrado (confirmados al reconsultar la página), desaparecido (dejó de salir, sin confirmar) y vendido_probable (estaba reservado la última vez que se vio y desapareció). Para "lo que se paga" cuentan vendido, vendido_probable y reservado.
Columnas clave: seller_type (particular/tienda), is_new (parece moto nueva), price_last, price_final, year, km, abs (1/0/vacío=desconocido), flags, dealer, dup_n, days_listed, price_changes, reserved_ever.

## Ámbito del análisis (scope)
Cada producto de `products.yml` puede llevar un bloque `scope` (variant, conditions, year, km, a2, max_days_listed). No cambia lo que se descarga: `clean.py` marca `in_scope` 1/0 en `data/clean/<id>.csv`. Los informes usan `in_scope==1` salvo que Pablo pida otra ventana. Dato desconocido no cumple year/km/conditions/variant; en a2 desconocido sí entra.

## Reglas
- Lo crudo no se edita ni se borra; todo lo derivado se rehace con clean.py.
- Wallapop: categoría motos = 14000; el filtro de precio mínimo (mitad del valor razonable) quita recambios.
- Los vendidos pierden año/km en su página: solo valen los datos capturados mientras estaban activos (details).
- Si cambias extract.py o clean.py, ejecuta `python3 clean.py` y revisa el CSV antes de subir.
