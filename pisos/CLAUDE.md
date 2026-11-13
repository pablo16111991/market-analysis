# pisos (Fotocasa) — módulo de market-analysis

Pisos en venta de Fotocasa. Rutas relativas a `pisos/` (datos en `pisos/data/`). Solo Fotocasa (Idealista bloquea con anti-bot; su API oficial requiere solicitud).

## Zona
186 municipios a ≤ 60 min en coche (sin tráfico, OSRM) de Pl. Catalunya, 150-350k, ≥ 2 hab (desde 2026-11-13; antes
solo Barcelona, Badalona, El Masnou, Premià y Mataró hasta 300k). Lista con minutos y km: `data/ref/municipios.csv`,
generada con `ref/build_zonas.py` (se ejecuta a mano). El id de la búsqueda sigue siendo `pisos-bcn-norte` por el histórico.
Las zonas nuevas no tienen histórico antes de esa fecha (tendencias y días publicado tardan semanas en valer).

## Estructura
- `pisos.yml`: búsquedas (zonas, min/max precio, min habitaciones, scope). Un bloque por búsqueda.
- `rawio.py`: lectura/escritura de lo crudo. Lo nuevo va en .gz (GitHub no acepta ficheros de más de 100 MB).
- `collect.py`: descarga diaria cruda. Pagina `.../viviendas/<zona>/todas-las-zonas/l[/N]?minPrice&maxPrice&minRooms` y lee `__initial_props__` (JSON). Escribe en `data/raw/`: `<run>_search.csv.gz` (foto diaria, una fila por anuncio; `_INCOMPLETO` si faltó >5% o alguna zona falló tras 2 reintentos; hasta 2026-11-13 `.csv` sin comprimir), `items/<run>.jsonl.gz` (anuncio completo, solo si es nuevo o cambió; el antiguo `items.jsonl` se lee pero ya no se escribe), `<run>_status.csv` (¿sigue existiendo lo que dejó de salir?: ficha con redirección `?propertyNotFound` = retirado; si existe, guarda su precio actual) y `<run>_details.csv` (ficha: certificado energético, features).
- `clean.py`: reconstruye `data/clean/<id>.csv` (1 fila por anuncio). Añade `ciudad`, `provincia`, `min_bcn`, `km_bcn` desde `municipios.csv` (por la zona buscada). Ojo: en Fotocasa `locality` = ciudad, `municipality` = distrito/zona dentro de la ciudad, `neighborhood` = barrio.

## Estados
activo, retirado (la ficha ya no existe: vendido o retirado por el dueño, Fotocasa no distingue), fuera_de_filtro (sigue publicado con otro precio fuera del filtro), desaparecido (dejó de salir, sin comprobar aún).

## Ámbito (in_scope)
Siempre fuera: ocupado/okupa (bandera de Fotocasa o texto), nuda propiedad/usufructo (bandera o texto), subasta, y duplicados (el mismo piso repetido: se unen los anuncios que cumplan A) mismo punto a ~10 m, superficie, habitaciones, baños, planta y subtipo, y precio a menos de un 1 %, o B) mismo barrio, precio exacto, superficie, habitaciones, baños y subtipo, si son 3 o más, o 2 de la misma agencia; `dup_n` = tamaño del grupo, `dup_group` = id del principal, que es el único en ámbito: el activo de id más bajo). `plantilla`=1 si el grupo tiene 10 o más: son redes de agencias (La Casa Agency, ~40 % de los anuncios activos) que publican la misma ficha con muchas cuentas; el principal sigue en ámbito, pero conviene tratarlo con cautela, puede no ser un piso real. Alquilados con inquilinos SÍ entran (columna `rented`). Del yml: `min_surface` (50 m²), `subtypes`, `exclude_neighborhoods` (barrios que Pablo descarta; ahora Sant Roc de Badalona y El Raval de Barcelona, escritos como `Ciudad/Barrio` porque hay barrios con el mismo nombre en otras ciudades).
Renta de la zona (INE, 2024; tablas de Barcelona, Girona y Tarragona): `renta_idx` (100 = media de Barcelona ciudad, 20.326 €/persona; mediana de los pisos del barrio, o de su distrito si el barrio tiene <5 pisos), `renta_idx_seccion` (por piso, coordenadas aproximadas) y `nivel_zona` (1-5 con cortes 75/90/110/135, que dejan ~59 % de los pisos en nivel 1 porque 150-300k cae en zonas de renta baja: mejor filtrar con `min_renta_idx` en el scope). Datos en `data/ref/` (se regeneran con `python3 pisos/ref/build_renta.py`). Filtros opcionales del scope, hoy desactivados: `min_renta_idx`, `min_nivel_zona`.
Columnas de aviso sin excluir: `a_reformar`, `rented`, `drop_pct`, `days_listed`, `eur_m2`.
`antiquity`, `conservation`, `orientation` son códigos numéricos de Fotocasa, aún sin traducir.

## Interpretación
Percentiles sobre `in_scope==1`; precio y €/m² por zona/barrio. Siempre indicar n (n<10 orientativo). Para "¿se pueden apretar?": comparar con vecinos de mismo barrio/superficie/estado, mirar `days_listed`, `price_changes`, `drop_pct`. `retirado` mezcla vendido y retirado.
Fichas: cada ejecución baja las que faltan (tope `FICHAS_MIN` = 120 min; lo que quede, al día siguiente; al ampliar la zona hay ~18.000 pendientes, una semana larga). El workflow tiene 240 min de tope. Comprobación de retirados: tope 20 min.
Snapshots: pueden existir varias ejecuciones el mismo día (manuales o de respaldo). No se borra nada de lo crudo; `runs_seen` cuenta días distintos, no ejecuciones.
