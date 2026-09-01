# ADR-001: Formato de `standards.yml` como fuente de TEAM-STANDARDS.md

**Status:** Proposed
**Date:** 2026-09-01
**Deciders:** Luis Cruz
**Parte de:** TRD py-attest · PRD v0.3 §7.1, §11.1

## Context

`TEAM-STANDARDS.md` es el contrato central de py-attest: lo leen humanos (es casi el único archivo que un usuario edita/forkea, per PRD §5), y lo consumen tres piezas de código — el prompt del LLM reviewer (reglas `mode: llm`), `gating.py` (severidad por regla), y `attest doctor`/`lint-standards` (reglas `mode: deterministic`, cross-referenciadas contra checks instalados).

El seed (`student-progress-seed`) escribió este archivo a mano en Markdown con una convención implícita (severidades S1/S2/S3, IDs tipo `6-S2-logic-bug` embebidos en el título de cada hallazgo). Funciona para un repo, pero generalizarlo expone tres problemas: (1) un parser de Markdown-con-convención es frágil — cualquier reformateo humano rompe el parsing; (2) no hay forma barata de validar el archivo (`lint-standards` tendría que reimplementar el parser antes de poder validar nada); (3) no hay mecanismo claro para que `attest upgrade` actualice el núcleo universal sin pisar las reglas de dominio del usuario (PRD §7: "las secciones de dominio son del usuario, generadas con ejemplo comentado, en bloques que el merge de Copier respeta" — pero "bloques marcados" en Markdown es un mecanismo que hay que inventar y mantener).

Restricción de producto ya fijada (PRD §5, R5): cada regla declara ID estable, severidad (S1/S2/S3), y modo de enforcement (`deterministic`/`llm`/`human`). El TRD debe decidir la gramática concreta.

## Decision

`standards.yml` es la fuente de verdad, en dos archivos con ciclos de vida distintos, combinados por `attest standards build` en un único `TEAM-STANDARDS.md` generado:

- **`core.standards.yml`** — núcleo universal, entregado y actualizado por el template vía `attest upgrade` (Copier update normal, 3-way merge).
- **`domain.standards.yml`** — reglas del usuario, creado una sola vez con un ejemplo comentado, y marcado `_skip_if_exists` en `copier.yml` — una característica real de Copier para archivos que se generan una vez y nunca se vuelven a tocar en `update`. Esto reemplaza por completo la idea de "bloques marcados estilo git" del PRD original: en vez de fusionar texto dentro de un archivo compartido, son dos archivos con dueños distintos.

`TEAM-STANDARDS.md` lleva un encabezado "GENERADO — no editar a mano, edita `domain.standards.yml`", y un check de CI regenera y compara (`attest standards build --check`); si el committed diverge del generado, falla. El Markdown nunca puede desincronizarse de lo que el código realmente aplica.

### Gramática (JSON Schema, resumida)

```yaml
version: 1
sections:
  - slug: testing              # kebab-case, agrupa reglas en el MD generado
    title: Testing
    rules:
      - id: testing-2          # único global (core + domain combinados), estable de por vida
        title: Tests must be able to fail
        severity: S2           # S1 | S2 | S3
        mode: llm               # deterministic | llm | human
        description: >          # texto que lee el humano Y que se inyecta al prompt si mode:llm
          Tests that cannot detect a regression (trivial assertions, fully
          mocked logic, no coverage of the business case) do not count as
          test coverage.
        rationale: >             # el "por qué" — mini-ADR inline, solo en el núcleo
          A coverage gate cannot catch a test that executes a line and
          asserts nothing meaningful; only a reviewer that reads the
          assertion can.
      - id: testing-1
        title: Untested core logic fails CI
        severity: S2
        mode: deterministic
        check: coverage-gate     # referencia a un check del catálogo de py-attest
        description: >
          Every logic change includes tests that fail if the behavior breaks.
```

`domain.standards.yml` generado por el template (ejemplo comentado, editable/borrable):

```yaml
version: 1
sections:
  - slug: pii
    title: "PII and logging (ejemplo — edita o borra esta sección)"
    rules:
      - id: pii-1
        title: PII must not reach logs
        severity: S1
        mode: llm
        description: >
          PII (full_name, email, birthdate) must not be written to logs,
          directly or indirectly. Use app.privacy.redact().
```

**Cambio de diseño respecto al seed, y por qué importa:** los hallazgos del LLM reviewer emiten `rule_id`, no severidad propia. La severidad se resuelve por lookup contra el registro cargado de `standards.yml`, nunca se confía en lo que el modelo declara. Esto cierra en el diseño el modo de falla documentado en `EVAL.md` del seed (el único falso positivo del golden set fue inflación de severidad S3→S2 *por el modelo*). Un `rule_id` que no existe en el registro es un fallo de validación de schema — visible, degrada a COMMENT, nunca se aprueba en silencio.

## Options Considered

### Option A: Markdown como fuente, parseado con convención ligera (propuesta original, PRD v0.1-v0.2)

| Dimensión | Evaluación |
|---|---|
| Complejidad | Media — requiere escribir y mantener un parser de Markdown tolerante a reformateo humano |
| Validación | Difícil — `lint-standards` depende de que el parser no se rompa primero |
| Legibilidad humana | Alta — es el formato final, sin paso de generación |
| Mecanismo de núcleo/dominio | Sin resolver — requeriría inventar "bloques marcados" y enseñarle a Copier a respetarlos |

**Pros:** cero paso de build; lo que ves es lo que hay.
**Contras:** un parser de Markdown-con-convención es frágil por naturaleza (dos espacios de más rompen la extracción); no hay JSON Schema posible sin normalizar primero; el mecanismo núcleo/dominio queda sin resolver.

### Option B: YAML fuente → Markdown generado, dos archivos (core/domain) — **elegida**

| Dimensión | Evaluación |
|---|---|
| Complejidad | Media — un generador Jinja simple + JSON Schema, ambos triviales de testear |
| Validación | Alta — `lint-standards` valida contra JSON Schema, sin parsear prosa |
| Legibilidad humana | Alta en el artefacto final (el MD generado es lo que se lee en PRs); el YAML es implementación |
| Mecanismo de núcleo/dominio | Resuelto de fábrica — `_skip_if_exists` de Copier, sin inventar nada |

**Pros:** precedente sólido (Semgrep: reglas YAML con metadata a escala de miles de reglas); severidad centralizada cierra el failure mode del seed; construir el prompt del reviewer es un filtro (`mode == llm`), no un parser; `doctor` cruza `check` contra su catálogo sin ambigüedad.
**Contras:** dos archivos en vez de uno; escribir una regla nueva a mano requiere conocer la forma YAML (mitigado con un helper `attest standards new-rule`, ver Action Items); riesgo de que alguien edite el MD generado directamente — mitigado por el check de CI que regenera y compara.

### Option C: YAML/JSON puro, sin Markdown generado (solo config, docs aparte)

| Dimensión | Evaluación |
|---|---|
| Complejidad | Baja |
| Validación | Alta |
| Legibilidad humana | Baja — nadie revisa un PR leyendo YAML de reglas |
| Mecanismo de núcleo/dominio | Resuelto igual que Option B |

**Pros:** el más simple de implementar.
**Contras:** rompe el requisito de producto explícito (PRD §5, R5 y la premisa original de Luis: "el contrato lo leen humanos primero, una regla que nadie lee no gobierna nada"). Descartada por eso, no por técnica.

### Option D: TOML como formato fuente

| Dimensión | Evaluación |
|---|---|
| Complejidad | Media — mismo generador, distinto parser |
| Ecosistema | TOML ya es el formato de `pyproject.toml`; consistencia visual con el resto del repo |
| Expresividad para listas anidadas | Peor que YAML — arrays de tablas en TOML son más verbosos para `sections → rules` anidado |

**Pros:** encaja con la elección de `[tool.attest]` en pyproject.toml para configuración de runtime.
**Contras:** TOML es incómodo para estructuras anidadas de profundidad 3 (sections→rules→campos); YAML es el estándar de facto para "reglas declarativas" en el ecosistema (Semgrep, GitHub Actions, pre-commit-hooks) — más reconocible para quien vaya a escribir reglas de dominio.

## Trade-off Analysis

La decisión real no es YAML-vs-Markdown en abstracto — es **dónde vive la fuente de verdad para tres consumidores automatizados distintos** (prompt, gating, doctor) que hoy tendrían que parsear prosa para extraer datos estructurados. Mover esa estructura a YAML no le quita nada al lector humano (el MD generado es indistinguible en calidad de uno escrito a mano) y le da a todo el sistema de tooling un contrato validable. El costo real — dos archivos, un paso de generación — es pequeño y ya tiene precedente operativo en el propio ecosistema Python (`pyproject.toml` generado por herramientas, `poetry.lock` como derivado, etc.). El mecanismo `_skip_if_exists` de Copier resuelve gratis el problema que motivó explorar "bloques marcados" — es la pieza que hace que Option B gane con margen sobre Option A, no solo el argumento de validación.

## Consequences

- **Más fácil:** `lint-standards` es validación de JSON Schema, no parsing de prosa; construir el prompt del reviewer es un filtro de una línea; `doctor` cruza `check` contra su catálogo sin ambigüedad; `attest upgrade` nunca toca `domain.standards.yml` por construcción, no por disciplina; la severidad inflada por el modelo (el único FP del golden set) queda estructuralmente cerrada.
- **Más difícil:** escribir una regla de dominio a mano requiere conocer la forma YAML — se mitiga con `attest standards new-rule <sección> <título>` (Action Item, P1); riesgo de edición directa del MD generado — mitigado por el check de CI, no eliminado del todo (UX: el encabezado del MD debe ser inequívoco).
- **A revisar más adelante:** soporte multi-lenguaje (fuera de alcance v1, PRD non-goal) tocaría este schema — reservar un campo opcional `applies_to` sin implementarlo ahora, para no cerrar la puerta.

## Action Items

1. [ ] Escribir JSON Schema de `standards.yml` (sections, rules, patrón de `id`, enums de `severity`/`mode`) en el paquete `py-attest`.
2. [ ] Implementar `attest standards build` (merge `core.standards.yml` + `domain.standards.yml` → `TEAM-STANDARDS.md` vía plantilla Jinja).
3. [ ] Implementar `attest lint-standards` (validación de schema + IDs únicos global core+domain + reglas `deterministic` con `check` en el catálogo conocido).
4. [ ] Marcar `domain.standards.yml` como `_skip_if_exists` en `copier.yml` del template.
5. [ ] Añadir a los workflows generados un job de CI que corre `attest standards build --check` (regenera y compara; falla si diverge).
6. [ ] Actualizar el schema de salida del LLM reviewer: los findings emiten `rule_id`; severidad y modo se resuelven por lookup contra el registro cargado, nunca se confían del output del modelo; `rule_id` desconocido = fallo de validación de schema.
7. [ ] (P1) `attest standards new-rule` — scaffolding de una regla nueva en `domain.standards.yml` con los campos requeridos ya presentes.
