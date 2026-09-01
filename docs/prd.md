# PRD v0.3 — py-attest

**Producto:** `py-attest` — CLI de scaffolding y quality gate para repos Python
**Estado:** Cerrado para el TRD — sin preguntas de producto bloqueantes pendientes · **Autor:** Luis Cruz (con Claude) · **Fecha:** 2026-09-01
**Cambios vs v0.2:** las 4 preguntas de producto bloqueantes resueltas (orden de F1, default del gate IA, licencia, ubicación de config); las 4 decisiones técnicas bloqueantes resueltas como pre-ADRs (formato TEAM-STANDARDS.md, interfaz de proveedor LLM, import name, compatibilidad paquete↔template); handles de GitHub y colisión de binario verificados.

---

## 1. Problem statement

Los templates de proyecto (Cookiecutter y derivados) generan un repo y se despiden: la configuración de calidad que instalan —lint, testing, CI, reglas de PR— es una foto que envejece y se erosiona. Las herramientas de revisión IA existentes (CodeRabbit, Greptile, Qodo) son cajas negras: no publican precision/recall, el veredicto lo emite el modelo y no una política auditable, no están enfocadas en calidad de tests, y el código viaja a un tercero. Y todo el ecosistema de scaffolding sirve solo a repos nuevos, cuando el universo de repos existentes es órdenes de magnitud mayor.

El costo de no resolverlo: cada proyecto nuevo re-paga el setup de calidad (~días), los estándares dependen de quién revisa cada PR, y no existe evidencia verificable de que el proceso de revisión funciona.

**Evidencia:** el gap fue validado construyendo el motor completo (ejercicio Open English, ago 2026): gate por capas con eval publicado — 100% recall de bloqueo (6/6), 87.5% accuracy de veredicto en el golden set. Ninguna herramienta comercial publica métricas equivalentes.

## 2. Visión y objetivo

**Una herramienta que instala y mantiene actualizado, en cualquier repo Python —nuevo o heredado—, un estándar de calidad verificable: checks deterministas y un revisor IA cuya precisión está medida y publicada, para que el repo mismo sea la evidencia de cómo trabaja su autor.**

Attest = dar fe. El gate no opina: certifica contra un contrato explícito (`TEAM-STANDARDS.md`) y sus números están publicados.

Proyecto open-source (MIT), construido en abierto al estilo Tequio: DECISIONS.md, evals publicados, self-hosting (los PRs de py-attest pasan por py-attest).

## 3. Goals

1. **G1 — Setup en minutos:** de `attest new` a primer PR gateado en < 15 min (medido de clean clone, ya validado en el seed: 66 s el quickstart).
2. **G2 — Adopción en repos existentes:** `attest doctor` produce un reporte accionable sobre cualquier repo Python sin requerir regeneración ni adopción total.
3. **G3 — Confianza medible en el revisor IA:** cada release del motor publica precision/recall contra el golden set; regresión dura: recall de bloqueo S1/S2 = 100%.
4. **G4 — Actualizable sin dolor:** el núcleo de calidad llega a repos ya generados vía `attest upgrade` (Copier update) y `pip install -U`, respetando cambios locales.
5. **G5 — Portfolio:** el repo demuestra el modo de trabajo del autor ante evaluadores técnicos (métrica blanda: menciones/uso en entrevistas y outreach).

## 4. Non-goals (v1)

- **Otros lenguajes (Node, Go):** duplica la capa de calidad antes de validarla. El diseño del reporte de `doctor` deja la puerta abierta (checks de proceso son agnósticos).
- **GitHub App / SaaS propio:** el gate corre en el CI del usuario con su API key. Un servicio hosteado es otra escala de responsabilidad (uptime, acceso a código de terceros).
- **UI web / dashboard:** la CLI y los artefactos markdown/JSON son la interfaz. Un dashboard no responde ninguna pregunta que el reporte no responda.
- **Motor de templating propio:** Copier resuelve generación + update con merge de 3 vías. Reinventarlo es el error clásico de esta categoría.
- **Auto-fix del doctor en v1:** reportar primero, aplicar después (F3). Un auto-fix prematuro que rompe repos mata la confianza que es el producto entero.
- **Telemetría:** ninguna. Adopción se mide por señales públicas (stars, clones, issues).

## 5. Usuarios y user stories

**P1 — Dev individual / freelancer** (usuario #1: Luis)
- Como dev arrancando un proyecto, quiero `attest new` con variante (lambda/fastapi/django) para tener en minutos un repo donde ya puedo escribir lógica de negocio con la infraestructura de calidad instalada.
- Como dev sin API key configurada, quiero que todo lo determinista funcione igual y el revisor IA falle con un mensaje claro, para no depender de un proveedor para trabajar.
- Como dev, quiero que `make gate` local corra exactamente lo que corre CI, para no descubrir fallas hasta el PR.

**P2 — Tech lead de equipo pequeño**
- Como tech lead, quiero editar solo `TEAM-STANDARDS.md` para definir las reglas de mi dominio, sin tocar el motor ni los workflows.
- Como tech lead, quiero que los hallazgos del gate citen IDs de regla de mi estándar, para que las discusiones de PR refieran al contrato y no a opiniones.
- Como tech lead, quiero `attest calibrate` para comprobar que el gate atrapa los canarios en MI repo con MI modelo, antes de hacerlo required check.
- Como tech lead, quiero `attest upgrade` con diff visible para adoptar mejoras del núcleo sin perder mis personalizaciones.

**P3 — Mantenedor de repo existente/legacy**
- Como mantenedor, quiero `attest doctor` sobre mi repo actual para saber qué me falta contra el estándar (paridad local/CI, coverage gate, reglas sin enforcement) sin regenerar nada.
- Como mantenedor, quiero adoptar piezas incrementalmente (solo el gate, solo los checks) sin all-or-nothing.

**P4 — Evaluador técnico (lector del repo)**
- Como evaluador, quiero ver EVAL.md y DECISIONS.md para juzgar el rigor del autor con evidencia y no con claims.

**Edge cases que las stories deben cubrir:** repo sin git, repo sin tests, diff que excede el límite del LLM, key inválida/rate limit, TEAM-STANDARDS malformado, conflicto de merge en upgrade, secreto en el diff (firewall), PR limpio (true negative — el gate debe saber callarse).

## 6. Requirements

### P0 — Must have (sin esto no hay v1)

| ID | Requirement | Criterios de aceptación (resumen) |
|---|---|---|
| R1 | **Motor como paquete pip** (`py-attest` en PyPI): reviewer LLM con salida estructurada, validación de schema, postfilter de evidencia (degrade-not-drop), `gating.py` (veredicto por tabla, nunca por el modelo), firewall de secretos pre-LLM. | Dado un diff con secreto, gitleaks bloquea y no hay llamada LLM. Dado un hallazgo sin evidencia verificable, se degrada a `confidence=low` visible, nunca se borra. Exit codes: 0 approve/comment, 2 block. |
| R2 | **Capa de proveedor LLM agnóstica**: el usuario configura proveedor/modelo/key; sin key, todo lo determinista corre y el reviewer termina con mensaje claro (nunca stack trace). | Dado `attest gate` sin key, lint+tests+secrets corren y el resultado lo dice explícitamente. |
| R3 | **Golden set como regresión del motor**: los 8 PRs del seed corren en el CI del paquete; release bloqueado si recall de bloqueo S1/S2 < 100%. | `make eval` reproduce las métricas publicadas byte a byte desde clean clone. |
| R4 | **`attest new`** (variante FastAPI primero): genera repo vía Copier con pre-commit, ruff, mypy, pytest+coverage gate, gitleaks, workflows CI, plantilla de PR, CODEOWNERS, TEAM-STANDARDS.md, Makefile con paridad local/CI. | Dado `attest new` en máquina limpia con Python 3.11+, el repo generado pasa su propio `attest gate` sin ediciones, en <15 min incluyendo instalación. |
| R5 | **TEAM-STANDARDS.md parseable**: reglas con ID estable, severidad (S1/S2/S3), modo (`deterministic`/`llm`/`human`); núcleo universal versionado + secciones de dominio del usuario preservadas en upgrade. | `attest lint-standards` rechaza IDs duplicados, severidades inválidas, reglas `deterministic` sin check instalado. Los hallazgos del gate citan IDs de regla. |
| R6 | **`attest gate`**: pipeline completo local y en CI (un solo motor, dos modos), reportes md+JSON estampados con versión de prompt, modelo, config. | Mismo diff → mismo veredicto local vs CI (tolerancia de variancia documentada del seed). Diff > límite degrada a COMMENT con explicación, no falla. |
| R7 | **Self-hosting**: los repos `py-attest` y `py-attest-template` corren su propio gate en cada PR desde F1. | Badge y artefactos de review visibles en PRs reales del proyecto. |

### P1 — Should have (fast follow)

| ID | Requirement | Criterios de aceptación (resumen) |
|---|---|---|
| R8 | **`attest upgrade`**: envuelve `copier update`; muestra diff, respeta secciones de dominio del estándar y cambios locales; conflictos en marcadores estilo git. | Upgrade de template vN a vN+1 sobre repo con personalizaciones conserva las secciones de usuario; el CI del template incluye este escenario como test. |
| R9 | **`attest doctor` v1 (solo reporte)**: audita repo existente — paridad local/CI, coverage gate activo, workflows presentes/actualizados, estándar válido, reglas S1 con enforcement. Salida md+JSON con severidades. | Corre sobre un repo arbitrario Python sin configuración previa y produce reporte sin modificar nada. |
| R10 | **Variantes lambda y Django** en el template. | Cada variante generada pasa su propio gate sin ediciones. |
| R11 | **Calibración de severidad en el prompt** (fix del FP conocido: inflación S3→S2). | El caso score-validation del golden set deja de bloquear sin perder recall. |

### P2 — Future (diseñar sin construir)

- **`attest doctor --fix`**: aplicar remediaciones con confirmación por ítem.
- **`attest calibrate`**: sembrar PRs canario (bug escudado por tests triviales, secreto, PR limpio) y verificar que el gate del usuario los atrapa. Los canarios se etiquetan contra IDs de regla.
- **Reporte doctor multi-lenguaje** (checks de proceso agnósticos).
- **Registro de núcleos de estándar alternativos** (p. ej. un núcleo "data science" vs "backend").

## 7. Arquitectura de producto (decidida)

**Dos repos, dos canales de actualización:**

- **`py-attest`** (GitHub + PyPI): CLI (`new`, `upgrade`, `doctor`, `gate`, `calibrate`, `lint-standards`) + motor del gate + eval harness con golden set. SemVer vía releases PyPI. Bugfixes llegan con `pip install -U` sin tocar archivos del usuario.
- **`py-attest-template`** (GitHub, consumido por Copier vía git): esqueleto por variante, `copier.yml`, workflows, Makefile, pre-commit, plantilla de PR, núcleo de TEAM-STANDARDS.md. Versionado por git tags (Copier los usa para descubrir versiones — razón mecánica de la separación: los tags de PyPI releases y de template chocan en un monorepo).

**Conexión:** el repo generado pina `py-attest>=X,<Y` en su pyproject; sus workflows llaman `attest gate`; la CLI trae la URL del template por default.

**Nombre y handles — verificados 2026-09-01:**
- `py-attest` libre en PyPI (existe `attest` 0.5.3, librería de testing abandonada de la era Python 2: usa `use_2to3`, no instala con pip moderno — riesgo de colisión de binario nulo en la práctica).
- **Import:** `py_attest` (nunca `attest`, evita cualquier ambigüedad con el paquete viejo). **Binario/comando:** `attest`. **Paquete PyPI:** `py-attest`.
- Repos `github.com/luicruz01/py-attest` y `github.com/luicruz01/py-attest-template` — ambos nombres libres, confirmado.

**Decisiones técnicas bloqueantes — pre-ADRs (formalizar con `engineering:architecture` en el TRD):**

1. **TEAM-STANDARDS.md se genera, no se edita a mano.** Fuente de verdad: `standards.yml` (cada regla: id, severidad, modo `deterministic`/`llm`/`human`, texto, rationale; para las deterministas, el check que la verifica). `attest standards build` genera el Markdown legible con encabezado "GENERADO — edita standards.yml". Un check de CI regenera y compara; si difieren, falla — mantiene el doc siempre en sync sin fiarse de la disciplina humana. Precedente: es el mismo patrón que usa Semgrep (reglas YAML con metadata). `lint-standards` valida contra JSON Schema, no contra un parser de Markdown.
2. **Interfaz de proveedor LLM propia y mínima, no litellm por default.** litellm-el-SDK es una librería (no un servicio: no se "levanta" nada en CI), pero es una dependencia pesada para lo poco que necesitamos: mandar un prompt, recibir JSON validado contra schema. v1: interfaz propia (~100 líneas por proveedor, como ya existe en el seed para OpenAI) con OpenAI y Anthropic soportados. litellm queda como extra opcional (`pip install py-attest[litellm]`) si algún usuario lo pide, nunca impuesto.
3. **Import name `py_attest`, comando `attest`, paquete `py-attest`.** Estándar del ecosistema (scikit-learn/sklearn, beautifulsoup4/bs4): el nombre de PyPI, el nombre de import y el nombre del binario son independientes.
4. **Compatibilidad paquete↔template por rangos SemVer declarados, no por esperanza.** El template genera `py-attest>=X,<Y` en el pyproject de cada repo; `attest doctor` compara lo que los workflows instalados esperan contra lo que está realmente instalado y señala desalineación; cambio que rompe CLI o schema del reporte = major del motor, y el template que lo adopta sube su propio major. `attest upgrade` actualiza el rango junto con los workflows.

## 8. Success metrics

**Leading (semanas):**
- Quickstart < 15 min de clean clone (medido en CI con job de quickstart cronometrado; el seed logró 66 s).
- `attest doctor` corre sin error sobre ≥ 8/10 repos Python OSS populares elegidos como prueba (test del supuesto de adopción, pre-lanzamiento).
- Variancia de veredicto local vs CI: 8/8 en golden set (ya logrado en seed; mantener como regresión).

**Lagging (meses):**
- Señales públicas: ≥ 100 stars combinadas o ≥ 3 issues/PRs de terceros en 3 meses post-lanzamiento (umbral de "alguien más lo usa"; stretch: un adoptante externo con el gate como required check).
- Retención del gate: el propio Luis lo usa en cada proyecto nuevo (si el autor lo esquiva, el producto falló — métrica honesta #1).
- ≥ 1 mención con tracción del contenido de lanzamiento (reportes de doctor sobre repos conocidos, historia TrueHome→py-attest).

## 9. Open questions

**Cerradas 2026-09-01 (decisiones de producto):**
1. ~~Orden F1~~ → **Template primero.** Es lo que Luis necesita para uso propio de inmediato; el doctor y su experimento de validación de adopción quedan en F2.
2. ~~Gate IA opt-in/opt-out~~ → **Activado por default en `new`**, con degradación limpia (mensaje claro, no stack trace) cuando no hay API key configurada.
3. ~~Licencia~~ → **MIT**, consistente con Tequio.
4. ~~Config del usuario~~ → **`[tool.attest]` en `pyproject.toml`**, siguiendo la convención de ruff/mypy/pytest — nada nuevo que el usuario tenga que aprender a encontrar.

**Cerradas 2026-09-01 (pre-ADRs técnicos, ver §7):** formato de TEAM-STANDARDS.md (YAML→MD generado), interfaz de proveedor LLM (propia, no litellm por default), import name (`py_attest`/`attest`/`py-attest`), compatibilidad paquete↔template (rangos SemVer + doctor). Formalizar como ADRs en el TRD con `engineering:architecture`.

**Aún abiertas — no bloqueantes, resolver durante F1-F2:**
5. *(eng)* Catálogo v1 de checks del `doctor`: lista concreta con severidad y método de detección de cada uno. Es también la base de las reglas `deterministic` del núcleo de `standards.yml`.
6. *(eng)* Modelo de seguridad formal: manejo de keys (env only — ya decidido en el seed), qué sale del repo y cuándo, threat model del postfilter (matching por substring no es frontera de seguridad, ya señalado en EVAL.md).
7. *(eng)* Toolchain de build del paquete (¿uv + hatchling?) y matriz de versiones Python soportadas.
8. *(eng)* Árbol de preguntas de `copier.yml` por variante y estrategia de tags/versionado del template.

## 10. Fases y timeline

Sin deadline duro externo; el forcing function es tener F0-F1 utilizables para los propios proyectos de Luis y material publicable. Licencia MIT en ambos repos desde el primer commit.

- **F0 — Extracción del motor** (cirugía, no invención): `tools/quality_gate/` del seed → paquete `py-attest` (import `py_attest`, comando `attest`); interfaz de proveedor propia (OpenAI + Anthropic); golden set como CI de regresión; publicar a PyPI. Repos creados: `luicruz01/py-attest`, `luicruz01/py-attest-template`.
- **F1 — Template + CLI mínima (prioridad — uso propio inmediato):** variante FastAPI, `new` + `gate`, gate IA on por default con degradación sin key, `standards.yml` → TEAM-STANDARDS.md generado + `lint-standards`, config en `[tool.attest]`, self-hosting.
- **F2 — Actualizable + auditable:** `upgrade` (rangos SemVer + diff), `doctor` v1 (reporte, catálogo v1 de checks), experimento de doctor sobre 10 repos OSS (valida la tesis de adopción antes de invertir más en doctor).
- **F3 — Cobertura:** variantes lambda/Django, `doctor --fix`, `calibrate`.
- **F4 — Lanzamiento:** README nivel Tequio, posts (TrueHome → py-attest), reportes doctor como contenido.

## 11. Rumbo al TRD — qué falta definir y detallar

El PRD ya no tiene preguntas de producto pendientes. Lo que queda es especificar en detalle las 4 decisiones técnicas del §7 (formalizarlas como ADRs) y cerrar las 4 preguntas técnicas no bloqueantes del §9. Concretamente, el TRD debe producir:

1. **Spec completa de `standards.yml`:** JSON Schema de la gramática (campos por regla, tipos de `mode`, formato de ID), ejemplos válidos/inválidos, suite de fixtures para `lint-standards`, y el template Jinja/generador que produce TEAM-STANDARDS.md desde el YAML.
2. **Contratos de la CLI:** firma de cada comando (flags, exit codes, formatos de salida md/JSON con schemas), comportamiento sin red/sin key/sin git.
3. **Diseño del paquete:** layout de módulos al extraer del seed (qué se renombra, qué API es pública), toolchain de build (¿uv + hatchling?), matriz de versiones Python soportadas.
4. **Interfaz de proveedor LLM:** el Protocol/ABC exacto (structured output, retries, timeouts, costos), implementaciones OpenAI/Anthropic v1, manejo de la restricción de temperatura documentada en el seed.
5. **`copier.yml` del template:** árbol de preguntas por variante, valores condicionales, estrategia de tags/versionado del template y test de upgrade en CI.
6. **Catálogo de checks del doctor v1:** lista con severidad y método de detección de cada uno — es también la base de las reglas `deterministic` del núcleo de `standards.yml`.
7. **Modelo de seguridad:** manejo de keys (env only), qué sale del repo y cuándo (solo el diff, nunca en presencia de secretos), threat model del postfilter (ya señalado en el seed: matching por substring no es frontera de seguridad).
8. **Mecánica exacta de rangos SemVer:** dónde se declara el rango en el pyproject generado, cómo `doctor` detecta desalineación, cómo `upgrade` lo actualiza.

Con el nombre, los repos, la licencia y las 4 decisiones de producto cerrados, el siguiente paso natural es abrir el TRD formalizando los pre-ADRs del §7 con `engineering:architecture`, empezando por el de `standards.yml` — es del que cuelgan más de los otros.

---
*Historial: v0.1 (2026-09-01, brainstorm inicial) → v0.2 (2026-09-01, nombre py-attest, estructura de spec completa) → v0.3 (2026-09-01, PRD cerrado: preguntas de producto resueltas, pre-ADRs técnicos definidos, handles verificados). Derivado del seed `student-progress-seed` (motor + EVAL.md + DECISIONS.md) e investigación de ecosistema (Copier/cruft/projen/Backstage, revisión IA).*
