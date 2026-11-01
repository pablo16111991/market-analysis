# second-hand (Wallapop)

Descarga diaria de Wallapop (GitHub Actions) para varios productos, con datos crudos y limpieza aparte.

- `products.yml` define qué buscar. Para añadir un producto, copia un bloque.
- `collect.py` descarga y solo añade ficheros a `data/raw/` (todos los productos juntos, columna `product`).
- `clean.py` reconstruye `data/clean/<producto>.csv` desde lo crudo (un anuncio por fila, con su último estado:
  activo, reservado, vendido, caducado, borrado o desaparecido).
- `extract.py` extrae marca, modelo, año, km, ABS y señales de descarte (reglas).
