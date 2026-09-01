# Plan de implementación con Claude Code — py-attest

**Estado:** v0.1 · **Fecha:** 2026-09-01 · **Base:** PRD v0.3, ADR-001/002/003, TRD v0.1
**Objetivo de este documento:** convertir el TRD en una secuencia ejecutable con Claude Code (CC): qué repos crear, en qué orden, qué corre en paralelo, qué contexto reciben los agentes, qué prompt abre cada sesión, y qué plugins habilitar.

---

## 1. Principios de trabajo con CC (los que evitan el caos)

1. **Los documentos viven en el repo, no en el chat.** PRD, ADRs y TRD se commitean en `docs/` desde el primer commit. `CLAUDE.md` es corto y apunta a ellos; el agente lee el ADR que le toca, no un resumen.
2. **Un paquete de trabajo = una sesión de CC = un PR.** Cada WP del TRD §11 tiene un prompt de apertura (§6), una definición de terminado (DoD) y un PR. Nunca dos WPs en la misma rama.
3. **Paralelo solo cuando el TRD lo permite, y siempre en worktrees.** `git worktree add ../py-attest-wp-f0.3 -b wp/f0.3` y una sesión de CC por worktree. Las sesiones no comparten estado; lo que comparten es `main` y los docs.
4. **El agente no decide arquitectura.** Si un WP descubre que un ADR está mal, el output correcto es un comentario en el PR + propuesta de cambio al ADR, no un workaround silencioso. Esto va en `CLAUDE.md`.
5. **TDD por defecto** (skill `superpowers`): los tests del seed se migran primero y deben pasar antes de tocar el código migrado.
6. **Bootstrap de revisión:** hasta que py-attest se auto-hospede (F1.3), los PRs de py-attest se revisan con `pr-review-toolkit` en local y con Claude Code Action en GitHub. Desde F1.3, con `attest gate`.

## 2. Repositorios y su comunicación

| Repo | Contenido | Se crea en | Depende de |
|---|---|---|---|
| **`luicruz01/py-attest`** | motor + CLI + eval + `docs/` (PRD, ADRs, TRD, este plan) | Paso 0 | seed (solo lectura) |
| **`luicruz01/py-attest-template`** | template Copier + CI cruzado | Paso 4 (tras `v1.0.0` en PyPI) | py-attest publicado |
| seed `student-progress-seed` | referencia de solo lectura; su `tools/quality_gate/` y `tests/quality_gate/` se copian a py-attest en F0.2; sus 8 PRs se graban como fixtures del golden set en F0.5 | ya existe | — |

**Comunicación entre repos** (ADR-003): el template declara `attest_engine_range`; el motor no sabe nada del template. El CI del template instala el motor mínimo del rango y genera un repo de prueba; el CI del motor genera un repo con el último tag del template. Cada repo tiene el link al otro en su README y en `CLAUDE.md`.

**Repo generado de prueba** (`attest new` en el CI del template): efímero, no se crea como repo real.

## 3. Secuencia de ejecución (DAG)

```
Paso 0  Bootstrap py-attest (repo, docs, CLAUDE.md, plugins, CI vacío)        ── secuencial, humano + CC
   │
Paso 1  F0.1 esqueleto del paquete + exit codes + CI                          ── secuencial
   │
Paso 2  F0.2 migrar gate/ desde el seed con sus tests                          ── secuencial (todo depende de esto)
   │
   ├──────────────────────────┬────────────────────────┐
Paso 3a F0.3 llm/ (ADR-002)   Paso 3b F0.4 standards/  Paso 3c doctor/ subset  ── PARALELO, 3 worktrees
   │        (ADR-001) + gate resuelve severidad         (compat-*, standards-*)
   └──────────────────────────┴────────────────────────┘
   │  merge en orden: 3b → 3a → 3c (3c depende de 3b; 3a es independiente)
Paso 4  F0.5 golden set grabado + eval/ + job semanal                          ── secuencial (necesita 3a y 3b)
   │
Paso 5  F0.6 release v1.0.0 a PyPI                                             ── humano (tag) + CC (changelog)
   │
Paso 6  Bootstrap py-attest-template (repo, docs, CLAUDE.md)                   ── secuencial
   │
   ├──────────────────────────────────┐
Paso 7a F1.1 template fastapi         Paso 7b F1.2 `attest new` en py-attest   ── PARALELO, 2 repos distintos
   │  (copier.yml, árbol, workflows)      (necesita un template aunque sea local:
   │                                       usa 7a en curso vía --template ../py-attest-template)
   └──────────────────────────────────┘
Paso 8  F1.3 self-hosting en ambos repos                                       ── secuencial
   │
Paso 9  F1.4 quickstart cronometrado + docs de instalación                     ── secuencial → fin de F1
```

**Regla de merge en paralelo:** el worktree que termina primero abre PR y espera; los demás hacen `git rebase main` antes de abrir el suyo. El orden 3b → 3a → 3c evita que 3c (doctor, que usa el registro de standards) se escriba contra un registro que no existe todavía.

## 4. Paso a paso

### Paso 0 — Bootstrap `py-attest` (≈ 1 sesión)

Humano: crear el repo en GitHub (público, MIT, sin README), `git init`, habilitar plugins (§7), configurar branch protection en `main` (require PR, require status checks cuando existan).

CC (prompt P0 en §6): estructura inicial —

```
py-attest/
├── CLAUDE.md                 (§5.1)
├── docs/
│   ├── prd.md  trd.md  plan-cc.md
│   └── adr/001-standards-yml.md  002-llm-provider.md  003-compatibility.md
├── .claude/settings.json     hooks: ruff + pytest tras edición (§7.3)
├── .github/workflows/ci.yml  (vacío: lint + test que pasan en verde con 0 tests)
├── pyproject.toml            (hatchling, uv, extras vacíos, click)
├── LICENSE (MIT)  README.md (una frase + link a docs/)  .gitignore  .pre-commit-config.yaml
```

DoD: CI verde; `uv sync` funciona; `attest --version` imprime algo; `docs/` completo.

### Paso 1 — F0.1 Esqueleto y contratos de CLI (≈ 1 sesión)

CC implementa `py_attest/cli/main.py` con el grupo click, los seis comandos como stubs que imprimen "not implemented" y **la tabla de exit codes completa** (TRD §4.1) con un test por código, incluido el override de `UsageError` → 64. `config.py` con `[tool.attest]` + `ATTEST_*` y rechazo de claves desconocidas.

DoD: `pytest` verde con tests de exit codes; `attest gate` sin args sale 64; `attest doctor` sale 0 con "no checks registered".

### Paso 2 — F0.2 Migración del gate (≈ 1-2 sesiones)

Entrada: el seed en un directorio local (`../student-progress-seed`). CC copia `tools/quality_gate/*` → `py_attest/gate/` y `tests/quality_gate/*` → `tests/gate/` según el mapeo del TRD §3.1, **primero los tests** (deben fallar por imports), luego el código, hasta verde. Rutas hardcodeadas → `Config`. `review.py` se parte en `pipeline.py`, `diff.py`, `report.py`. Exit codes según TRD §4.1 (BLOCK=2, error=4).

DoD: todos los tests del seed pasan en su nueva casa; `attest gate --diff-file tests/gate/fixtures/streaks.patch --no-llm` produce JSON+md; sin referencia a `tools.quality_gate` en ningún import.

### Paso 3 — PARALELO (3 worktrees, 3 sesiones)

**3a — F0.3 `llm/` (ADR-002).** Types, Protocol, taxonomía de errores, `policy.py` (reintentos/timeouts/attempts), registro por entry points, proveedor OpenAI portado del seed, proveedor Anthropic nuevo (`tool_use` forzado), `ProviderContractTests` + fixtures grabadas. `gate/pipeline.py` consume `llm.registry` en lugar del cliente OpenAI directo. DoD: contract tests verdes para ambos; `attest gate` sin key → `layers.llm = skipped:no_provider_key`, exit 0.

**3b — F0.4 `standards/` (ADR-001).** `schema.json`, `registry.py`, `build.py` (Jinja → TEAM-STANDARDS.md, `--check`), `lint.py`; `core.standards.yml` inicial portando las secciones §1, §2, §5 del TEAM-STANDARDS.md del seed; `gate/schema.py` exige `rule_id` y `gating.py` resuelve severidad desde el registro. DoD: `attest standards build --check` y `attest standards lint` funcionan; fixtures de standards inválidos; el golden set del seed sigue produciendo los mismos veredictos con `rule_id` mapeados.

**3c — Doctor subset (TRD §6, solo `standards-valid`, `standards-in-sync`, `compat-*`).** `doctor/runner.py`, la clase base `Check`, `report.py`, los 4 checks. Se escribe contra la interfaz de `standards.registry` acordada en el TRD; se rebasea sobre 3b antes del PR. DoD: `attest doctor --compat` en un repo con answers file de prueba produce los 4 estados pass/fail con `remedy`.

### Paso 4 — F0.5 Golden set y eval (≈ 1 sesión)

CC graba las respuestas del proveedor para los 8 PRs del seed como fixtures (`eval/golden/<branch>/{diff.patch, provider_response.json, expected.json}`), migra `eval_metrics.py`, y escribe el job semanal (`eval-live.yml`, `workflow_dispatch` + cron) que corre contra proveedores reales y actualiza `EVAL.md`. DoD: `make eval` reproduce las métricas del seed byte a byte desde fixtures; el job de PR no toca la red.

### Paso 5 — F0.6 Release `v1.0.0`

Humano: tag `v1.0.0`, push. CC: CHANGELOG con sección "Compatibilidad" (ADR-003 §Action Items 8), workflow de publicación a PyPI por trusted publishing (`pypa/gh-action-pypi-publish`, sin tokens en secrets). Verificar `pipx install py-attest` desde PyPI en máquina limpia.

### Paso 6 — Bootstrap `py-attest-template`

Igual que Paso 0: repo, MIT, `docs/` (solo links al PRD/ADRs del motor + copia del ADR-003), `CLAUDE.md` propio (§5.2), CI vacío.

### Paso 7 — PARALELO (2 repos)

**7a — F1.1 Template fastapi.** `copier.yml` del TRD §7 (con `_skip_if_exists`, `attest_engine_range: ">=1.0,<2"`), árbol generado, `attest.yml` workflow, Makefile con paridad, `.pre-commit-config.yaml`, PR template desde reglas `human`, README generado. CI cruzado: generar con `--defaults` + motor mínimo + `attest gate` + `standards build --check` + escenario de upgrade con `domain.standards.yml` modificado. DoD: los 3 jobs del CI del template en verde.

**7b — F1.2 `attest new` + `doctor --compat` tras generar.** En py-attest, con extra `scaffold`; durante el desarrollo apunta a `--template ../py-attest-template` (path local del worktree de 7a). DoD: `attest new demo --variant fastapi --defaults --template <local>` genera un repo que pasa `attest gate --no-llm` y `attest doctor --compat`.

### Paso 8 — F1.3 Self-hosting

Ambos repos añaden el job `gate` de `attest.yml` a su propio CI, con `OPENAI_API_KEY` en secrets, y lo marcan como required check. Se retira Claude Code Action de revisión (o se deja como segunda opinión no bloqueante). DoD: el primer PR revisado por py-attest en py-attest queda enlazado en el README ("así se ve un review").

### Paso 9 — F1.4 Quickstart cronometrado + docs

Job en el CI del template que corre el quickstart completo y falla si supera 15 min; docs de instalación (`pipx install "py-attest[scaffold,openai]"`). Fin de F1.

## 5. Contexto para los agentes

### 5.1 `CLAUDE.md` de `py-attest` (esqueleto — mantener < 80 líneas)

```markdown
# py-attest

CLI + motor de quality gate para repos Python. Paquete PyPI `py-attest`, import `py_attest`, comando `attest`.

## Antes de tocar código
- Lee `docs/trd.md` §3 (layout) y §4 (contratos de CLI, exit codes). Los exit codes son un contrato: 0 ok/approve/comment · 2 BLOCK · 3 incompatibilidad · 4 error de ejecución · 64 uso.
- Decisiones cerradas en `docs/adr/`. Si un WP requiere contradecir un ADR: NO implementes un workaround; comenta en el PR y propone el cambio al ADR.
- El veredicto lo calcula `gate/gating.py` desde una tabla. Nunca el modelo. No cambies esto.

## Cómo trabajar
- TDD: tests primero. Los tests migrados del seed son la red de seguridad de F0.
- `uv sync --all-extras && uv run pytest` antes de cada commit. `ruff check` y `ruff format --check` deben pasar.
- Sin telemetría, sin llamadas de red fuera del proveedor LLM configurado. Sin keys en archivos.
- Un WP por rama (`wp/f0.3`). Commits pequeños con mensaje convencional.

## Mapa
- `py_attest/gate/` pipeline por capas (lint → tests → secrets firewall → llm → schema → postfilter → gating → report)
- `py_attest/llm/` ADR-002 · `py_attest/standards/` ADR-001 · `py_attest/doctor/` catálogo TRD §6
- `eval/` golden set (fixtures grabadas; el job semanal usa proveedores reales)

## Repos relacionados
- Template: github.com/luicruz01/py-attest-template (ADR-003 explica la compatibilidad)
```

### 5.2 `CLAUDE.md` de `py-attest-template`

Misma forma, con: qué es Copier y sus reglas (`_skip_if_exists`, `when: false`, tags), que `attest_engine_range` **se sube en el mismo PR** que use un flag nuevo del motor, que el CI del template genera un repo real y corre el gate, y que los archivos bajo `template/` son Jinja (cuidado con `{{ }}` en YAML de workflows: usar `{% raw %}`).

### 5.3 Otros archivos de contexto

- `docs/adr/README.md`: índice + convención para ADRs nuevos (siguiente número, plantilla del plugin `engineering:architecture`).
- `.claude/agents/reviewer.md` (opcional, F0.2+): subagente de revisión con el checklist de `TEAM-STANDARDS` del seed §1-§2-§5, para usar hasta el self-hosting.
- `CONTRIBUTING.md`: cómo correr el golden set, cómo grabar fixtures de proveedor nuevas, cómo subir `attest_engine_range`.

## 6. Prompts de apertura por sesión (copiar/pegar)

Cada prompt asume que el agente está en la raíz del repo, en la rama del WP, y que los docs están commiteados. Todos terminan igual: *"Al terminar, resume qué hiciste, qué tests añadiste, y qué dudas de diseño encontraste — no las resuelvas tú."*

**P0 — Bootstrap**
> Estás iniciando el repo `py-attest`. Lee `docs/trd.md` completo y `docs/adr/*.md`. Crea la estructura del Paso 0 de `docs/plan-cc.md` §4: pyproject (hatchling, hatch-vcs para versión desde tag, click, extras `scaffold`/`openai`/`anthropic`/`all` vacíos por ahora), `py_attest/__init__.py` con `__version__`, CI mínimo (ruff + pytest en 3.11/3.12/3.13 con uv), pre-commit (ruff, gitleaks), `.claude/settings.json` con los hooks de `docs/plan-cc.md` §7.3, README de una frase. No implementes comandos. Verifica `uv sync && uv run attest --version`.

**P1 — F0.1**
> Implementa `py_attest/cli/main.py` y `py_attest/config.py` según `docs/trd.md` §3.3 y §4.1-4.2. Los seis comandos existen como stubs. La tabla de exit codes es un contrato: escribe primero un test por cada código (0, 2, 3, 4, 64) usando `CliRunner`, incluido el override de `click.UsageError` → 64, y luego el código. `Config` rechaza claves desconocidas en `[tool.attest]`.

**P2 — F0.2**
> El seed está en `../student-progress-seed`. Migra `tools/quality_gate/` a `py_attest/gate/` siguiendo el mapeo exacto de `docs/trd.md` §3.1. Orden obligatorio: (1) copia `tests/quality_gate/*` a `tests/gate/` y ajusta imports — deben fallar; (2) copia el código y ajusta hasta verde, sin cambiar comportamiento; (3) reemplaza rutas hardcodeadas (`parents[2]`, `CONTEXT_FILES`) por `Config`; (4) parte `review.py` en `pipeline.py`/`diff.py`/`report.py`; (5) exit codes: BLOCK=2, error de ejecución=4 (el seed usaba 2 para ambos). No toques `llm.py` más allá de los imports — es el WP F0.3.

**P3a — F0.3** (worktree `wp/f0.3`)
> Implementa `py_attest/llm/` según `docs/adr/002-llm-provider.md` al pie de la letra: `types.py`, `policy.py`, `registry.py` (entry points `py_attest.providers`), `providers/openai.py` (porta el fallback de temperatura del seed a `temperature_applied`), `providers/anthropic.py` (`tool_use` forzado con `input_schema`). Escribe `ProviderContractTests` primero; ambos proveedores deben pasarla con fixtures grabadas (sin red en tests). Conecta `gate/pipeline.py` al registro; sin key → `layers.llm = "skipped:no_provider_key"` y exit 0.

**P3b — F0.4** (worktree `wp/f0.4`)
> Implementa `py_attest/standards/` según `docs/adr/001-standards-yml.md`: `schema.json`, `registry.py`, `build.py` (Jinja, `--check`), `lint.py`. Crea `core.standards.yml` portando las secciones 1, 2 y 5 del `TEAM-STANDARDS.md` del seed (`../student-progress-seed/TEAM-STANDARDS.md`) con IDs `code-quality-N`, `testing-N`, `secrets-N`, y un `domain.standards.yml` de ejemplo con la sección PII del seed. Cambia `gate/schema.py` para exigir `rule_id` y `gate/gating.py` para resolver severidad desde el registro. Fixtures de standards inválidos para `lint`.

**P3c — Doctor subset** (worktree `wp/doctor-compat`)
> Implementa `py_attest/doctor/` (runner, clase base `Check`, report md+JSON según `docs/trd.md` §4.4) con solo cuatro checks: `standards-valid`, `standards-in-sync`, `compat-engine-range`, `compat-pin-consistent` (`docs/adr/003-compatibility.md` §3). Programa contra la interfaz de `standards.registry` descrita en el TRD; antes de abrir PR, rebasea sobre `main` cuando F0.4 haya mergeado. Un fixture de repo por check en estado pass y fail.

**P4 — F0.5**
> Graba el golden set: para cada uno de los 8 PRs del seed (`../student-progress-seed/eval/`), guarda `diff.patch`, la respuesta del proveedor (`provider_response.json`, obtenida una vez con `OPENAI_API_KEY` real) y `expected.json` (veredicto y hallazgos esperados de `eval/ground_truth.yml`). Migra `eval_metrics.py`. El job de PR corre contra fixtures y debe reproducir las métricas de `EVAL.md` del seed; el job `eval-live.yml` (cron semanal + dispatch) corre contra proveedores reales y regenera `EVAL.md`.

**P7a — F1.1** (repo template)
> Implementa el template fastapi según `docs/trd.md` §7 y `docs/adr/003-compatibility.md`. `copier.yml` con `_skip_if_exists`, `attest_engine_range` como `when: false`. Los workflows generados son Jinja — envuelve el YAML de GitHub Actions en `{% raw %}`. CI del template: genera con `copier copy --defaults`, instala la versión mínima de `attest_engine_range`, corre `attest gate --no-llm`, `attest doctor --compat`, `attest standards build --check`; y un job que hace `copier update` de un tag anterior a HEAD sobre un repo con `domain.standards.yml` modificado y verifica que quedó intacto.

**P7b — F1.2** (repo py-attest)
> Implementa `attest new` según `docs/trd.md` §4.2 con el extra `scaffold` (copier). Sin el extra, imprime una línea con el comando de instalación y sale 64. Tras generar, corre `doctor --compat` en el destino. Prueba contra `--template ../py-attest-template`.

## 7. Plugins de Claude Code

### 7.1 Lo que tienes instalado

| Plugin | Estado actual | Recomendación | Por qué |
|---|---|---|---|
| `superpowers` | disabled | **Habilitar** | `/brainstorming` para dudas de diseño dentro de un WP, `/execute-plan` con checkpoints de revisión, TDD forzado (red→green→refactor) y debugging sistemático. Es el marco de trabajo de todo el plan. |
| `code-simplifier` | disabled | Habilitar solo en pasos de refactor (F0.2 fase 4) | Útil para limpiar `review.py` al partirlo; ruido en el resto. |
| `everything-claude-code` | disabled | Dejar deshabilitado | Colección enorme (13 agentes, 40+ skills) — mucho contexto que compite con los docs del proyecto. Superpowers cubre lo que necesitamos. |
| `frontend-design` | enabled | **Deshabilitar** para este proyecto | No hay frontend; cada plugin habilitado añade contexto a cada sesión. |
| `ui-ux-pro-max` | enabled | **Deshabilitar** para este proyecto | Idem. |

### 7.2 Del catálogo oficial (`claude-plugins-official`) — habilitar

| Plugin | Para qué en py-attest |
|---|---|
| **`pr-review-toolkit`** | Agentes de revisión especializados en tests, manejo de errores, diseño de tipos y calidad. Es la revisión de PRs hasta el self-hosting (Paso 8) — y después, segunda opinión no bloqueante. |
| **`pyright-lsp`** | Type checking e inteligencia de código Python en sesión. |
| **`commit-commands`** | `/commit`, push y creación de PR con el formato convencional que exige pre-commit (commitizen). |
| **`claude-md-management`** | Auditar `CLAUDE.md` y capturar aprendizajes de sesión al final de cada WP — mantiene el contexto de los agentes al día sin que crezca sin control. |
| **`security-guidance`** | Avisos por patrón al editar + revisión del diff al terminar. Estamos escribiendo un firewall de secretos; conviene que el propio agente tenga el reflejo. |
| **`hookify`** | Crear los hooks de §7.3 desde lenguaje natural si no quieres escribir el JSON a mano. |
| `context7` (external) | Documentación actualizada de Copier, click, jsonschema durante la implementación — evita APIs inventadas. |
| `code-review` | Alternativa a `pr-review-toolkit` (multi-agente con scoring por confianza). Elegir uno; recomiendo `pr-review-toolkit` por su agente específico de tests. |
| `feature-dev` | Workflow explorar→diseñar→implementar. Solapa con superpowers; opcional. |

No necesarios: `plugin-dev`, `skill-creator`, `mcp-server-dev`, LSPs de otros lenguajes, `ralph-loop` (los WPs son acotados; no queremos loops autónomos largos sobre un motor de seguridad).

### 7.3 Hooks recomendados (`.claude/settings.json`)

Tras cada edición de `*.py`: `uv run ruff check --fix <archivo> && uv run ruff format <archivo>`. Antes de cada commit (vía pre-commit, no hook de CC): ruff, gitleaks, commitizen. Al terminar la sesión (Stop): `uv run pytest -q` y mostrar el resultado. Estos hooks son exactamente los checks deterministas del gate — el agente vive bajo las mismas reglas que impondrá.

### 7.4 En GitHub, hasta el self-hosting

Claude Code Action (`anthropics/claude-code-action`) en ambos repos con un prompt corto: "revisa contra `docs/trd.md` §4.1 (exit codes) y ADRs; señala cualquier desviación de un ADR". Se retira o se vuelve no bloqueante en el Paso 8.

## 8. Checkpoints humanos (donde tú decides, no el agente)

| Después de | Verificas |
|---|---|
| Paso 2 | Que el gate migrado produce el mismo reporte que el seed para `streaks.patch` (diff de los JSON) |
| Paso 3 (merge de los 3) | Que el golden set sigue dando 6/6 BLOCK con `rule_id` mapeados — es el primer momento en que las tres piezas se tocan |
| Paso 5 | `pipx install py-attest` en máquina limpia; `attest --version`; `attest gate --no-llm` sobre un diff |
| Paso 7 | Generar un repo con el template, abrir un PR con un bug escudado por un test trivial, ver el BLOCK |
| Paso 8 | El primer PR auto-revisado — léelo como si fueras un usuario nuevo |

## 9. Riesgos del plan (no del sistema)

- **El paralelo del Paso 3 se pisa en `gate/pipeline.py`** (3a lo conecta al registro LLM, 3b cambia schema/gating). Mitigación: 3b toca `schema.py`/`gating.py`; 3a toca solo la sección de llamada al proveedor en `pipeline.py`; se declara en los prompts.
- **Fixtures de proveedor desactualizadas** cuando cambie el prompt. Mitigación: el job semanal las regraba con `workflow_dispatch` y un PR automático.
- **Contexto que crece**: docs largos en cada sesión. Mitigación: `CLAUDE.md` apunta al ADR/sección relevante; el prompt de cada WP nombra qué leer.

---
*v0.1 · 2026-09-01. Plugins verificados contra el marketplace oficial `anthropics/claude-plugins-official` (clone del 2026-09-01).*
