# market-analysis

Analizadores de precios de mercado de Pablo, sin servicios de pago. Responde en español, corto y directo.
Objetivo común: ver por cuánto lo ponen (activos) y por cuánto se vende de verdad (desaparecidos/vendidos), con snapshots diarios para ver la evolución. El precio es una conclusión, nunca una entrada: no uses el presupuesto de Pablo. Sus precios mínimo y máximo son filtros de limpieza.

## Módulos (cada uno tiene su CLAUDE.md, léelo antes de tocarlo)
- `second-hand/`: Wallapop (motos, pedal NUX…). Ver `second-hand/CLAUDE.md`.
- `pisos/`: pisos en venta de Fotocasa. Ver `pisos/CLAUDE.md`.
Para un módulo nuevo: carpeta nueva con su yml, collect.py, clean.py y `data/{raw,clean}`, y copiar un workflow `scrape-<módulo>.yml`.

## Reglas comunes
- Un workflow por módulo (`.github/workflows/scrape-second-hand.yml` 06:17 UTC y `scrape-pisos.yml` 07:17 UTC). Comparten `concurrency: repo-commits` (no corren a la vez) y cada uno solo hace commit de su carpeta.
- Lo crudo (`<módulo>/data/raw`) solo se añade; nunca se edita ni se borra (salvo petición explícita de Pablo para regenerar). Todo lo derivado (`clean`) se rehace desde lo crudo.
- Dos tipos de filtro: de descarga (irreversibles, mantenerlos amplios) y de ámbito `scope` (reversibles, marcan `in_scope`).
- Si cambias un clean.py o extract.py, ejecútalo y revisa el CSV antes de subir.
- Lanzar a mano: `gh api -X POST repos/pablo16111991/market-analysis/actions/workflows/scrape-pisos.yml/dispatches -f ref=main` (o `scrape-second-hand.yml`).
- Commits: no subas datos a medias mientras una descarga sigue corriendo.
