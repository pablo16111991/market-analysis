# second-hand (Wallapop) — módulo de market-analysis

Analizador de precios de Wallapop de Pablo. Todas las rutas son relativas a `second-hand/` (datos en `second-hand/data/`) (sin servicios de pago). Responde en español, corto y directo.

Objetivo: por cuánto lo ponen a la venta (activos) y por cuánto se vende (vendidos y reservados). El precio es una conclusión, nunca una entrada: no uses el presupuesto de Pablo. Sus precios mínimo y máximo son filtros de limpieza.

## Estructura
- `products.yml`: productos a seguir. Es el único sitio que se toca para añadir uno (ver cabecera del fichero).
- `collect.py`: descarga CRUDA diaria. Solo añade ficheros en `data/raw/<run_id>_{search,details,status}.csv` (todos los productos juntos, columna `product`). `search()` traduce el yml a parámetros de la API de Wallapop.
- `clean.py`: reconstruye `data/clean/<id>.csv` (1 fila por anuncio, último estado) desde TODO lo crudo. Se puede rehacer siempre.
- `extract.py`: reglas de extracción. Extractor `moto` (variante, cc, año, km, ABS, A2, quickshifter, flags) y `generic` (marca, modelo, estado). Señales de tienda en `SHOP_RE`.
- `../.github/workflows/scrape.yml` (en la raíz del repo): Actions diario para TODOS los módulos (second-hand + pisos + commit). Lanzar a mano: `gh api -X POST repos/pablo16111991/market-analysis/actions/workflows/scrape.yml/dispatches -f ref=main`.

## Dos tipos de filtro en products.yml
1. **Descarga (irreversibles)**: `query`, `category`, `min_price`, `max_price`, `distance_km`, `lat/lon`, `max_pages`. Los aplica Wallapop en su servidor: lo que queda fuera no se guarda nunca. Mantenerlos amplios.
2. **Ámbito `scope` (reversibles)**: `variant` (texto o lista de variantes), `conditions`, `year`, `km`, `a2`, `max_days_listed`. No cambian lo descargado: `clean.py` marca `in_scope` 1/0. Los informes usan `in_scope==1` salvo que Pablo pida otra ventana. Dato desconocido no cumple year/km/conditions/variant; en a2 desconocido sí entra. Si Pablo cambia de ventana, edita el scope y ejecuta `clean.py`.
Otros campos: `extractor` (moto|generic) y `variants` (solo motos: `{name, brand, match (regex), cc}`; sin tocar código).

## Productos actuales
kymco-k-xct-125 y kymco-super-dink-125 (configuración idéntica: toda España, mín 1500, scope km 20.500-30.500; la Super Dink es la moto más parecida y se compara a posteriori, no se mezcla en la descarga), triumph-trident-660 (300 km, 4000-7000, scope 2021-2024, 10-25k km, A2), nux-mg-30 (toda España, 120-220, scope estado nuevo/como nuevo/buen estado), yamaha-tracer-7 (300 km, 4000-9000, scope 2021-2024, 10-25k km, A2).

## Estados en clean.csv
activo, reservado, vendido, caducado, borrado (confirmados al reconsultar la página), desaparecido (dejó de salir, sin confirmar) y vendido_probable (estaba reservado la última vez que se vio y desapareció). Para "lo que se paga" cuentan vendido, vendido_probable y reservado. `state` es derivado: cambiar la regla no requiere volver a descargar.
Columnas clave: in_scope, seller_type (particular/tienda), is_new (parece nuevo), condition (estado declarado en Wallapop), price_last, price_final, state, days_listed, price_changes, dup_n, distance_km, region, fav_por_visita (favoritos/visitas, foto de la 1ª vez que se vio; fiable con ≥100 visitas); en motos year, km, a2, quickshifter, abs, variant. Campo vacío = desconocido, no "no".

## Cómo se interpreta
- Percentiles 15/25/50/75/90 sobre `in_scope==1`, `is_new=0` (salvo en productos cuyo scope admite estado `new`, p. ej. la NUX: ahí no se excluye por is_new), ponderando 1/dup_n. Las tiendas NO se excluyen: se reportan aparte con `seller_type`.
- Por separado: lo que piden (activos, `price_last`) y lo que se paga (estados de arriba, `price_final`). Siempre indicar n; con n<10 es orientativo y con n<5 solo la lista.
- Los vendidos pierden año/km en su página: solo valen los datos capturados mientras estaban activos (details). El precio de un vendido es el último publicado, no el negociado.

## Reglas
- Lo crudo no se edita ni se borra (salvo petición explícita de Pablo para regenerar); todo lo derivado se rehace con clean.py.
- Wallapop: categoría motos = 14000; instrumentos musicales = 12463.
- Si cambias extract.py o clean.py, ejecuta `python3 second-hand/clean.py` (desde la raíz del repo) y revisa el CSV antes de subir.
