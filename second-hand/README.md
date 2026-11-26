# second-hand (Wallapop)

> **Pausado temporalmente (26-11-2026).** Por ahora está paralizado todo el módulo: no hay descargas de ningún producto.
> El código y los datos se conservan para reutilizarlo en el futuro.
>
> Para reactivarlo:
> 1. Deja en `products.yml` los productos que quieras seguir. Si quitas uno, `clean.py` rehará su CSV limpio sin extractor ni scope (lo crudo no cambia).
> 2. Activa el workflow: `gh api -X PUT repos/pablo16111991/market-analysis/actions/workflows/scrape-second-hand.yml/enable`
> 3. Activa la tarea programada «Lanzar scrape-second-hand».

Cuando está activo, hace una descarga diaria de Wallapop (GitHub Actions) para varios productos, con datos crudos y limpieza aparte.

- `products.yml` define qué buscar. Para añadir un producto, copia un bloque.
- `collect.py` descarga y solo añade ficheros a `data/raw/` (todos los productos juntos, columna `product`).
- `clean.py` reconstruye `data/clean/<producto>.csv` desde lo crudo (un anuncio por fila, con su último estado:
  activo, reservado, vendido, caducado, borrado o desaparecido).
- `extract.py` extrae marca, modelo, año, km, ABS y señales de descarte (reglas).
