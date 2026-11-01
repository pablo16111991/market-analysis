# market-analysis

Analizadores de precios de mercado de Pablo, sin servicios de pago. Responde en español, corto y directo.
Objetivo común: ver por cuánto lo ponen (activos) y por cuánto se vende de verdad (desaparecidos/vendidos), con snapshots diarios para ver la evolución. El precio es una conclusión, nunca una entrada: no uses el presupuesto de Pablo. Sus precios mínimo y máximo son filtros de limpieza.

## Módulos (cada uno tiene su CLAUDE.md, léelo antes de tocarlo)
- `second-hand/`: Wallapop (motos, pedal NUX…). Ver `second-hand/CLAUDE.md`.
- `pisos/`: pisos en venta de Fotocasa. Ver `pisos/CLAUDE.md`.
Para un módulo nuevo: carpeta nueva con su yml, collect.py, clean.py y `data/{raw,clean}`, y añadir un paso en `.github/workflows/scrape.yml`.

## Reglas comunes
- Un solo workflow (`.github/workflows/scrape.yml`, cron diario 06:17 UTC): cada módulo en su paso; los pisos con `continue-on-error` para no tumbar los demás.
- Lo crudo (`<módulo>/data/raw`) solo se añade; nunca se edita ni se borra (salvo petición explícita de Pablo para regenerar). Todo lo derivado (`clean`) se rehace desde lo crudo.
- Dos tipos de filtro: de descarga (irreversibles, mantenerlos amplios) y de ámbito `scope` (reversibles, marcan `in_scope`).
- Si cambias un clean.py o extract.py, ejecútalo y revisa el CSV antes de subir.
- Lanzar el workflow a mano: `gh api -X POST repos/pablo16111991/market-analysis/actions/workflows/scrape.yml/dispatches -f ref=main`.
- Commits: no subas datos a medias mientras una descarga sigue corriendo.
