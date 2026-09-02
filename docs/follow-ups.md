# Follow-ups

Hallazgos identificados durante el desarrollo pero deliberadamente diferidos (no bloquean lo que los originó, no se pierden). Un hallazgo se retira de esta lista solo cuando se resuelve en un commit — nunca por limpieza.

## De la revisión final de F0.4 (PR #5, `wp/f0.4`)

Seis hallazgos de la revisión de rama completa (`docs/superpowers/specs/2026-09-01-standards-and-review-validation-design.md`) que se decidió no arreglar en esa misma tanda de fixes.

### 1. `_fingerprint` (report.py) y `merge_findings` (postfilter.py) usan identidades distintas

- **Qué:** `report.py::_fingerprint` hashea `rule_id|path|side|line_start|title`; `postfilter.py::merge_findings` deduplica por la tupla `(rule_id, path, side, line_start, line_end)`. Dos findings que sobreviven el merge por diferir solo en `line_end` colisionan en el mismo fingerprint.
- **Dónde:** `py_attest/review/report.py` (`_fingerprint`), `py_attest/review/postfilter.py` (`merge_findings`).
- **Por qué se difirió:** sin efecto observable hoy — nada en el pipeline actual lee o compara fingerprints entre ejecuciones.
- **WP futuro:** el que implemente `review/github_comment.py` (comentario idempotente en PR marcado ★ en TRD §3.1, aún sin WP asignado explícitamente en `docs/plan-cc.md`) — ese es el consumidor que necesitaría fingerprints estables y sin colisiones para no duplicar comentarios.

### 2. Orden de campos en `core.standards.yml` generado

- **Qué:** `_llm_rule()` construye el dict de cada regla LLM con `severity`/`severity_policy` después de `non_examples`, así que en el YAML generado esas reglas muestran `severity` al final en vez de cerca del principio (las reglas `deterministic` sí lo ponen tercero, antes de `description`).
- **Dónde:** `py_attest/standards/migrate_review_rules.py::_llm_rule`.
- **Por qué se difirió:** puramente cosmético — no afecta el schema, `lint`, ni `build --check` (ambos toleran cualquier orden de keys en YAML). El archivo lo lee un humano, así que el orden importa para legibilidad, pero no es funcional.
- **WP futuro:** ninguno específico; corregible la próxima vez que se toque `migrate_review_rules.py` (por ejemplo si Seed B publica una revisión del catálogo).

### 3. `defaults/TEAM-STANDARDS.md` sin salto de línea final

- **Qué:** el archivo generado no termina en `\n`.
- **Dónde:** causa raíz en la plantilla Jinja de `py_attest/standards/build.py` (no usa `keep_trailing_newline=True`).
- **Por qué se difirió:** CommonMark lo tolera sin romper nada; solo se nota en editores que marcan "no newline at end of file".
- **WP futuro:** ninguno específico.

### 4. Nombre de test impreciso en `test_standards_cli.py`

- **Qué:** `test_standards_build_exits_64_on_a_schema_violation` usa en realidad un fixture de YAML inválido (no un incumplimiento del JSON Schema) — la aserción es correcta (ambos casos terminan en exit 64), solo el nombre describe mal el escenario.
- **Dónde:** `tests/test_standards_cli.py`.
- **Por qué se difirió:** no bloquea nada, es una imprecisión de nombre, no de comportamiento.
- **WP futuro:** ninguno específico.

### 5. `domain.standards.yml` se etiqueta "ejemplo" pero es operativo por el fallback

- **Qué:** el archivo generado dice `"(example -- edit or delete this section)"`, pero `reviewer.py::_standards_paths` lo usa como registro real (con fallback a `py_attest/standards/defaults/`) para cualquier repo que no tenga su propio `domain.standards.yml` — incluyendo sus reglas S1 que bloquean el merge (`pii-1`, `pii-2`, `retention-2`, `retention-3`). Un repo que borra deliberadamente ese archivo (siguiendo la instrucción del propio comentario "edit or delete") recupera silenciosamente las reglas de ejemplo por el fallback.
- **Dónde:** `py_attest/review/reviewer.py::_standards_paths` (el mecanismo de fallback) + `py_attest/standards/defaults/domain.standards.yml` (la etiqueta).
- **Por qué se difirió:** es una decisión de producto legítima y ya documentada — el fallback existe precisamente para que `attest review` funcione sin configuración previa (spec F0.4 §5.3). Pero la etiqueta "ejemplo, bórralo" y la consecuencia real (bloquea merges) tiran en direcciones opuestas. El propio revisor final de F0.4 lo enmarcó explícitamente como "para un WP futuro, no este".
- **WP futuro:** `attest new`/`attest upgrade` (F1.2 en `docs/plan-cc.md`). Cuando esos comandos existan, hace falta una decisión explícita: ¿el fallback a `defaults/` debe seguir aplicando después de que un repo pasó por `attest new`? ¿debería la etiqueta "ejemplo" cambiar una vez que el repo tiene su propio `domain.standards.yml` generado?

### 6. Campos faltantes del schema del reporte JSON (TRD §4.3)

- **Qué:** `meta` en el reporte JSON no incluye `standards_schema_version`, `template_version`, `attempts`, `usage`, `estimated_cost_usd` — todos documentados en el schema de TRD §4.3.
- **Dónde:** `py_attest/review/report.py::build_json_report`.
- **Por qué se difirió:** son huecos preexistentes de F0.2 (antes de que F0.4 existiera), fuera del alcance de este WP. `standards_schema_version` es el más relevante ahora que `standards/` existe y tiene una noción real de versión de schema — candidato natural para completarse a continuación.
- **WP futuro:** sin asignar explícitamente en `docs/plan-cc.md` todavía; probablemente F0.5 (golden set/eval, que consume el reporte JSON) o un WP dedicado a cerrar brechas de F0.2.
