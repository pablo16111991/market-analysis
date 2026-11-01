# pisos (Fotocasa) — módulo de market-analysis

Pisos en venta de Fotocasa. Rutas relativas a `pisos/` (datos en `pisos/data/`). Solo Fotocasa (Idealista bloquea con anti-bot; su API oficial requiere solicitud).

## Estructura
- `pisos.yml`: búsquedas (zonas, min/max precio, min habitaciones, scope). Un bloque por búsqueda.
- `collect.py`: descarga diaria cruda. Pagina `.../viviendas/<zona>/todas-las-zonas/l[/N]?minPrice&maxPrice&minRooms` y lee `__initial_props__` (JSON). Escribe en `data/raw/`: `<run>_search.csv` (foto diaria, una fila por anuncio; `_INCOMPLETO` si faltó >5%), `items.jsonl` (anuncio completo, solo si es nuevo o cambió), `<run>_status.csv` (¿sigue existiendo lo que dejó de salir?: ficha con redirección `?propertyNotFound` = retirado; si existe, guarda su precio actual) y `<run>_details.csv` (ficha: certificado energético, features).
- `clean.py`: reconstruye `data/clean/<id>.csv` (1 fila por anuncio).

## Estados
activo, retirado (la ficha ya no existe: vendido o retirado por el dueño, Fotocasa no distingue), fuera_de_filtro (sigue publicado con otro precio fuera del filtro), desaparecido (dejó de salir, sin comprobar aún).

## Ámbito (in_scope)
Siempre fuera: ocupado/okupa (bandera de Fotocasa o texto), nuda propiedad/usufructo (bandera o texto), subasta, y duplicados (de cada grupo se queda el de id más bajo). Alquilados con inquilinos SÍ entran (columna `rented`). Del yml: `min_surface` (50 m²), `subtypes`, `exclude_neighborhoods` (barrios que Pablo descarta; ahora Sant Roc y El Raval).
Renta de la zona (INE, 2024): `renta_idx` (100 = media de Barcelona ciudad, 20.326 €/persona; mediana de los pisos del barrio, o de su distrito si el barrio tiene <5 pisos), `renta_idx_seccion` (por piso, coordenadas aproximadas) y `nivel_zona` (1-5 con cortes 75/90/110/135, que dejan ~59 % de los pisos en nivel 1 porque 150-300k cae en zonas de renta baja: mejor filtrar con `min_renta_idx` en el scope). Datos en `data/ref/` (se regeneran con `python3 pisos/ref/build_renta.py`). Filtros opcionales del scope, hoy desactivados: `min_renta_idx`, `min_nivel_zona`.
Columnas de aviso sin excluir: `a_reformar`, `rented`, `drop_pct`, `days_listed`, `eur_m2`.
`antiquity`, `conservation`, `orientation` son códigos numéricos de Fotocasa, aún sin traducir.

## Interpretación
Percentiles sobre `in_scope==1`; precio y €/m² por zona/barrio. Siempre indicar n (n<10 orientativo). Para "¿se pueden apretar?": comparar con vecinos de mismo barrio/superficie/estado, mirar `days_listed`, `price_changes`, `drop_pct`. `retirado` mezcla vendido y retirado.
Fichas: cada ejecución baja las que faltan (tope 40 min; lo que quede, al día siguiente). Comprobación de retirados: tope 20 min.
