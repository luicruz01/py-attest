# TRD v0.1 — py-attest

**Producto:** `py-attest` (paquete PyPI, import `py_attest`, comando `attest`) + `py-attest-template` (template Copier)
**Estado:** Borrador para revisión · **Autor:** Luis Cruz (con Claude) · **Fecha:** 2026-09-01
**Base:** PRD v0.3 · ADR-001 (standards.yml) · ADR-002 (proveedor LLM) · ADR-003 (compatibilidad paquete↔template)
**Cubre:** diseño del paquete, contratos de la CLI, pipeline del gate, catálogo v1 de checks del doctor, template, modelo de seguridad, estrategia de pruebas, plan de implementación F0-F1.

---

## 1. Requisitos que gobiernan el diseño

**Funcionales** (PRD §6): R1 motor como paquete (gate por capas, veredicto por tabla, degrade-not-drop, firewall de secretos) · R2 proveedor configurable y degradación limpia sin key · R3 golden set como regresión · R4 `attest new` (FastAPI en F1) · R5 `standards.yml` parseable y validable · R6 `attest gate` un motor, dos modos (local/CI) · R7 self-hosting · R8 `upgrade` · R9 `doctor` (solo reporte en v1).

**No funcionales:**

| Requisito | Valor | Origen |
|---|---|---|
| Instalación en CI ligera | base sin SDKs de LLM ni Copier; extras por uso | ADR-002, Luis (peso en CI) |
| Paridad local/CI | el workflow y el Makefile invocan exactamente el mismo comando | PRD G1, R6 |
| Determinismo | mismo diff + misma config → mismo veredicto (variancia solo en la capa LLM, acotada por la trust policy) | EVAL.md del seed |
| Sin telemetría | ninguna llamada de red que no sea al proveedor LLM elegido o a git/PyPI/GitHub por acción explícita del usuario | PRD non-goal |
| Python | 3.11 – 3.13 (3.11 mínimo: el seed ya lo exige; `tomllib` en stdlib) | seed |
| Tiempo del gate en CI | ≤ 3 min sin LLM en repo pequeño; la llamada LLM acotada a 120 s × intentos | ADR-002 |
| Offline | `doctor --offline`, `gate` sin key: todo lo determinista corre | R2, ADR-003 |

**Restricciones:** un mantenedor; el seed ya funciona y está medido (F0 es extracción, no invención); Copier como motor de templating (no se reinventa); dos repos (ADR-003).

## 2. Arquitectura de alto nivel

```
 máquina del dev                          repo del usuario (generado o existente)
 ┌──────────────────────┐                 ┌─────────────────────────────────────────┐
 │ pipx/uvx py-attest   │  attest new     │ pyproject.toml  [tool.attest]           │
 │   [scaffold,openai]  │ ──────────────► │                 .[attest] = py-attest…  │
 │                      │  (Copier copy)  │ core.standards.yml ◄─ upgrade           │
 │ attest upgrade ──────┼───────────────► │ domain.standards.yml (skip_if_exists)   │
 │ attest doctor        │  (Copier update)│ TEAM-STANDARDS.md (generado)            │
 │ attest gate --branch │                 │ .github/workflows/attest.yml ─┐         │
 └──────────┬───────────┘                 │ Makefile: gate/test/lint      │         │
            │                             └───────────────────────────────┼─────────┘
            │  mismo binario, mismo comando                               │ CI
            ▼                                                             ▼
 ┌────────────────────────────────── py_attest (motor) ──────────────────────────────┐
 │ cli ─► config ─► standards.registry ─► gate.pipeline                              │
 │        pipeline: lint → tests+cov → secrets(gitleaks) ─firewall─► llm.review       │
 │                  → schema.validate → postfilter → gating.verdict → report(md/json) │
 │ llm.providers: openai | anthropic | <entry points>        (ADR-002)                │
 │ doctor.checks: catálogo v1 (§6)                                                    │
 └───────────────────────────────────────────────────────────────────────────────────┘
            │ git (diff, rev-parse)      │ gitleaks (binario)     │ HTTPS → proveedor LLM
```

**Flujo de datos de `attest gate`** (§5 en detalle): diff de git → capas deterministas → si hay secreto, BLOCK sin transmisión → si no, *context pack* (standards `mode: llm` + archivos de referencia configurados + diff) → proveedor → `raw_json` → validación de schema (con `rule_id` resuelto contra el registro) → postfilter de evidencia → tabla de política → veredicto + artefactos.

## 3. Diseño del paquete `py-attest`

### 3.1 Layout de módulos (mapeo desde el seed)

```
py_attest/
├── __init__.py            __version__ (leída de metadata)
├── cli/                   click; un módulo por comando
│   ├── main.py            grupo raíz, manejo global de errores → exit codes (§4.1)
│   ├── new.py  upgrade.py  doctor.py  gate.py  standards.py  calibrate.py (P2, stub)
├── config.py              carga [tool.attest] + overrides ATTEST_*; dataclass Config
├── standards/             ADR-001
│   ├── schema.json        JSON Schema de standards.yml
│   ├── registry.py        carga core+domain → Registry (rules by id, sections)
│   ├── build.py           Registry → TEAM-STANDARDS.md (Jinja); --check
│   └── lint.py            validación + cross-checks contra doctor.checks
├── gate/
│   ├── pipeline.py        orquestación de capas y degradaciones      ← review.py (main)
│   ├── diff.py            git diff base...branch / --diff-file        ← review.py (_branch_diff)
│   ├── context_pack.py    ← context_pack.py (archivos desde config, no hardcodeados)
│   ├── secrets_gate.py    ← secrets_gate.py (sin cambios de fondo)
│   ├── schema.py          ← schema.py (+ rule_id, evidence_verified, filtered_out)
│   ├── postfilter.py      ← postfilter.py (sin cambios de fondo)
│   ├── gating.py          ← gating.py (TRUST_POLICY_V1; severidad desde Registry)
│   └── report.py          ← review.py (render_markdown) + JSON con provenance (ADR-003)
├── llm/                   ADR-002
│   ├── types.py           ReviewRequest/ReviewResponse/Usage, Provider Protocol, errores
│   ├── policy.py          reintentos, timeouts, attempts
│   ├── registry.py        entry points py_attest.providers
│   ├── prompts/           reviewer_v3.md (+ historial v1/v2 solo en eval/)
│   └── providers/openai.py  anthropic.py
├── doctor/
│   ├── runner.py          ejecuta checks, agrega reporte
│   ├── checks/            un módulo por check (§6), registro por id
│   └── report.py          md + JSON
└── eval/                  ← eval_metrics.py + golden set (fixtures grabadas); no se instala en el wheel
```

Principio: los archivos del seed se mueven casi intactos a `gate/` — cambian imports, rutas hardcodeadas (`parents[2]`, `CONTEXT_FILES`) que pasan a `Config`, y la resolución de severidad (ADR-001). Los tests del seed (`tests/quality_gate/*`) se mueven con ellos y son la primera red de seguridad de la extracción.

### 3.2 Toolchain y dependencias

| Decisión | Elección | Por qué |
|---|---|---|
| Build backend | `hatchling` | estándar, sin config exótica, soporta `dynamic = ["version"]` desde tag |
| Gestor de entorno del repo | `uv` (lockfile `uv.lock`) | velocidad en CI; el template también usa `uv` en los workflows |
| CLI | `click` | subcomandos, `CliRunner` para tests, ubicuo. Cuidado: exit code de uso (§4.1) |
| Config TOML | `tomllib` (stdlib) | Python ≥ 3.11 lo garantiza; cero deps |
| YAML | `pyyaml` (safe_load) | standards.yml y answers de Copier |
| Validación | `jsonschema` | standards.yml y reporte; el schema de salida del LLM se valida con el mismo motor (reemplaza el validador manual del seed) |
| Templating | `jinja2` | TEAM-STANDARDS.md generado |
| Versionado | tag `vX.Y.Z` → versión del wheel (`hatch-vcs`) | ADR-003 §5 |

**Extras** (`pyproject.toml`):

- base: `click`, `pyyaml`, `jsonschema`, `jinja2` — suficiente para `gate` (sin IA), `doctor`, `standards`.
- `scaffold`: `copier>=9` — requerido por `new` y `upgrade`. Se separa porque CI nunca lo necesita y Copier trae su propio árbol de dependencias. Sin él, `attest new` imprime una línea: `install with: pipx install "py-attest[scaffold]"`.
- `openai`, `anthropic`, `all` — ADR-002.

Recomendación de instalación en docs: dev → `pipx install "py-attest[scaffold,openai]"` (o `uvx`); CI → `uv sync --extra attest` en el repo generado (ADR-003 §2).

### 3.3 Configuración (`[tool.attest]`)

```toml
[tool.attest]
provider = "openai"                 # ADR-002
model = "gpt-5-mini"
max_diff_bytes = 61440
base_branch = "main"
context_files = ["app/models.py", "app/privacy.py"]   # referencias para el reviewer (el seed las tenía hardcodeadas)
standards = { core = "core.standards.yml", domain = "domain.standards.yml", output = "TEAM-STANDARDS.md" }
reports_dir = "reports/"
```

Overrides por entorno: `ATTEST_PROVIDER`, `ATTEST_MODEL`, `ATTEST_BASE_BRANCH`. Keys **solo** por entorno (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). `config.py` valida tipos y rechaza claves desconocidas (evita typos silenciosos).

## 4. Contratos de la CLI

### 4.1 Exit codes (consolidados — el seed usaba 2 para BLOCK *y* para errores; se separan)

| Código | Significado | Quién lo emite |
|---|---|---|
| 0 | OK · `APPROVE` · `COMMENT` · doctor sin hallazgos S1 | todos |
| 2 | **BLOCK** — veredicto del gate; doctor con hallazgos S1 en `--strict` | `gate`, `doctor --strict` |
| 3 | **Incompatibilidad** motor↔template (ADR-003) | `upgrade`, `doctor --compat` |
| 4 | **Error de ejecución** — proveedor, git, gitleaks ausente, IO, schema del LLM inválido tras reintento | todos |
| 64 | **Error de uso** (`EX_USAGE`) — flags inválidos, config malformada | `cli/main.py` |

Click devuelve 2 en errores de uso por defecto — **colisiona con BLOCK**. `cli/main.py` captura `click.UsageError` y sale con 64. Es una línea, pero es un contrato: CI distingue "el gate dijo no" (2) de "el gate se rompió" (4) de "lo invocaste mal" (64).

### 4.2 Comandos

**`attest gate`** — `--branch <ref> | --diff-file <path>` (excluyentes, requerido) · `--base <ref>` (default: config) · `--out <dir>` · `--description <text>` (intención del autor; en CI, título+cuerpo del PR) · `--no-llm` (solo capas deterministas; también es el comportamiento automático sin key) · `--prompt-version <v>` (default: la empaquetada) · `--json` (imprime el reporte JSON a stdout además de escribirlo). Escribe `<out>/<safe-name>.json` y `.md`. Exit: 0/2/4/64.

**`attest doctor`** — `[path]` (default: cwd) · `--strict` (S1 → exit 2) · `--compat` (solo checks de compatibilidad, ADR-003) · `--offline` · `--json` · `--only <check-id,...>`. Nunca modifica archivos (v1). Exit: 0/2/3/4/64.

**`attest standards build`** — `--check` (regenera en memoria y compara con el committed; exit 2 si difiere) · **`attest standards lint`** — valida core+domain; exit 2 con lista de errores · **`attest standards new-rule <section> "<title>"`** (P1) — añade un esqueleto a `domain.standards.yml`.

**`attest new <dest>`** — `--variant fastapi|lambda|django` · `--template <url-or-path>` (default: `gh:luicruz01/py-attest-template`) · `--vcs-ref <tag>` · `--defaults` (no interactivo, para CI del template) · pasa el resto a Copier. Tras generar: `doctor --compat` en `<dest>`. Requiere extra `scaffold`. Exit: 0/3/4/64.

**`attest upgrade`** — `[path]` · `--vcs-ref` · `--defaults` · `--skip-answered` (Copier) · ejecuta `copier update` → rerender → `doctor --compat`; exit 3 si el motor queda fuera del rango nuevo; **nunca instala paquetes**. Exit: 0/3/4/64.

**`attest calibrate`** — P2; en v1 existe como stub que explica qué hará (evita que el nombre se lo lleve otro comando).

### 4.3 Schema del reporte del gate (JSON)

```jsonc
{
  "schema_version": 1,
  "verdict": "BLOCK",                    // APPROVE | COMMENT | BLOCK  — calculado por gating.py
  "exit_code": 2,
  "source": {"kind": "branch", "ref": "feature/streaks", "base": "main"},
  "layers": {                            // qué corrió y cómo terminó cada capa
    "lint": "pass", "tests": "pass", "secrets": "pass",
    "llm": "ran" | "skipped:no_provider_key" | "skipped:secret_detected" | "skipped:diff_too_large" | "skipped:--no-llm"
  },
  "findings": [{
    "rule_id": "testing-2",              // ADR-001; validado contra el registro
    "severity": "S2",                    // resuelta desde el registro, no del modelo
    "confidence": "high",
    "evidence_verified": true,
    "file": "app/streaks.py", "line": 10,
    "title": "...", "evidence": "...", "explanation": "...", "suggested_fix": "..."
  }],
  "filtered_out": [{"reason": "file_not_in_diff", "finding": {...}}],   // audit trail del postfilter, nunca se borra en silencio
  "summary": "...",
  "meta": {                              // provenance (seed + ADR-002 + ADR-003)
    "engine_version": "1.3.0", "template_version": "v1.5.0", "standards_schema_version": 1,
    "prompt_version": "v3", "provider": "openai", "model": "gpt-5-mini",
    "temperature_applied": "model-default", "attempts": 1, "usage": {"input_tokens": 0, "output_tokens": 0},
    "gate_commit": "699f43d", "generated_at": "2026-09-01T18:20:00Z"
  }
}
```

El markdown (`report.py`) se deriva del JSON (nunca al revés) y conserva el formato del seed: línea de provenance, veredicto, aviso de "human review requested" cuando hay S1/S2 a baja confianza, tabla de hallazgos, detalles, resumen. `verdict` en el md se recalcula desde `findings` con `gating.verdict` — el seed ya lo hacía así para que md y JSON no puedan contradecirse.

### 4.4 Schema del reporte del doctor (JSON)

```jsonc
{ "schema_version": 1, "path": ".", "engine_version": "1.3.0",
  "checks": [{"id": "compat-engine-range", "severity": "S1", "status": "fail" | "pass" | "skip",
              "message": "installed py-attest 1.2.0 is outside template range >=1.3,<2",
              "remedy": "pip install -U 'py-attest>=1.3,<2'", "rule_id": "…"}],   // rule_id si el check respalda una regla deterministic
  "summary": {"pass": 12, "fail": 1, "skip": 2} }
```

## 5. Pipeline de `attest gate` — detalle y degradaciones

| # | Capa | Implementación | Falla → |
|---|---|---|---|
| 1 | Resolver diff | `git diff --no-ext-diff base...branch` (o `--diff-file`) | git ausente / ref inválida → exit 4 |
| 2 | Lint | `ruff check` + `ruff format --check` | S3 → `COMMENT`, nunca BLOCK (TEAM-STANDARDS §6 del seed) |
| 3 | Tests + coverage | `pytest --cov` con `fail_under` del pyproject | fallo → `BLOCK` con hallazgo `testing-1` (deterministic) |
| 4 | Secrets (firewall) | gitleaks sobre el diff por stdin, `--redact` | leak → `BLOCK`, **la capa 6 no corre, el diff no se transmite**. gitleaks ausente → **exit 4** (la garantía de seguridad no se degrada en silencio; `doctor` avisa antes) |
| 5 | Tamaño | `len(diff) > max_diff_bytes` | `COMMENT: diff too large for AI review`, sin llamada |
| 6 | Proveedor | ADR-002; sin key → `layers.llm = skipped:no_provider_key`, veredicto por capas 2-4 | transitorio → reintentos; permanente → exit 4 |
| 7 | Validación | jsonschema + `rule_id ∈ Registry` | inválido → 1 reintento → exit 4 con `raw_json` guardado en `<out>/<name>.raw.json` |
| 8 | Postfilter | evidencia debe citar líneas añadidas; fragmentos con `...`; degrade-not-drop | `evidence_verified=false` → `confidence=low` (visible) |
| 9 | Veredicto | `TRUST_POLICY_V1[(severity, confidence)]`, máximo entre hallazgos | — |
| 10 | Artefactos | JSON + md + (opcional) comentario en PR desde el workflow | IO → exit 4 |

Las capas 2-3 se ejecutan vía subprocess con los mismos comandos que el Makefile generado — es la definición operativa de "paridad local/CI": **el Makefile llama `attest gate`, y `attest gate` llama a las herramientas**; no hay dos listas de comandos que mantener.

## 6. Catálogo v1 de checks del doctor

| id | Verifica | Método | Sev. | Respalda regla |
|---|---|---|---|---|
| `standards-valid` | core+domain cumplen el schema, IDs únicos, `check` conocidos | `standards.lint` | S1 | — |
| `standards-in-sync` | TEAM-STANDARDS.md == generado | `standards.build --check` | S2 | — |
| `compat-engine-range` | motor instalado ∈ `attest_engine_range` | ADR-003 §3 | S1 | — |
| `compat-pin-consistent` | rango en pyproject == answers | ADR-003 §3 | S2 | — |
| `template-outdated` | `_commit` < último tag (red) | `git ls-remote --tags`; skip en `--offline` | S3 | — |
| `coverage-gate` | `[tool.coverage.report].fail_under` presente y ≥ umbral del núcleo | parse pyproject | S2 | `testing-1` |
| `ruff-configured` | `[tool.ruff]` presente; pre-commit incluye ruff | parse pyproject + `.pre-commit-config.yaml` | S3 | `code-quality-*` |
| `gitleaks-available` | binario en PATH (local) / paso en workflow (CI) | `shutil.which` + parse workflow | S1 | `secrets-1` |
| `env-secrets-only` | `.env` en `.gitignore`, `.env.example` existe, ningún `.env` trackeado | git ls-files | S1 | `secrets-1` |
| `ci-parity` | cada target del Makefile invocado en CI existe, y CI no invoca comandos que no estén en el Makefile | parse Makefile + workflow | S2 | — |
| `pr-template` | `.github/pull_request_template.md` con checklist de reglas `mode: human` | existencia + IDs presentes | S3 | reglas `human` |
| `codeowners` | `CODEOWNERS` presente y no vacío | existencia | S3 | — |
| `python-pinned` | `requires-python` presente | parse pyproject | S3 | — |
| `tests-present` | `tests/` con ≥ 1 archivo `test_*.py` | fs | S2 | `testing-1` |
| `no-trivial-asserts` | funciones `test_*` sin `assert`/`pytest.raises`; `assert x is not None` como única aserción | AST (`ast.walk`) | S2 | `testing-2` (parcial: la parte determinista) |

Fuera de v1 (diseñar la salida para admitirlos): `branch-protection` (requiere token de GitHub), `mutation-smoke` (mutmut sobre un módulo), `dependency-audit` (pip-audit, hoy warn-only en el seed).

Cada check es una clase con `id`, `severity`, `run(ctx) -> CheckResult(status, message, remedy)`. `standards.lint` usa el mismo registro para verificar que toda regla `deterministic` apunte a un `check` existente (ADR-001).

## 7. Template `py-attest-template`

**`copier.yml`** (F1):

```yaml
_min_copier_version: "9.0"
_subdirectory: template
_skip_if_exists: ["domain.standards.yml", "CODEOWNERS", ".env.example"]
_answers_file: .copier-answers.yml

project_name: {type: str, help: "Nombre del proyecto (slug)"}
variant: {type: str, choices: [fastapi], default: fastapi}      # lambda, django en F3
python_version: {type: str, choices: ["3.11", "3.12", "3.13"], default: "3.12"}
ai_review: {type: bool, default: true, help: "Instalar el gate de revisión IA (requiere API key en CI)"}
llm_provider: {type: str, choices: [openai, anthropic], default: openai, when: "{{ ai_review }}"}
attest_engine_range: {when: false, default: ">=1.0,<2"}          # ADR-003
```

**Árbol generado** (variante fastapi): `app/` (main, models, settings), `tests/`, `pyproject.toml` (ruff, pytest, coverage `fail_under`, `[tool.attest]`, extra `attest`), `core.standards.yml`, `domain.standards.yml`, `TEAM-STANDARDS.md`, `Makefile` (`setup test lint gate doctor standards hooks`), `.pre-commit-config.yaml` (ruff, gitleaks, commitizen — como el seed), `.github/workflows/attest.yml`, `.github/pull_request_template.md` (checklist desde reglas `human`), `CODEOWNERS`, `.env.example`, `.gitignore`, `README.md`.

**Workflow generado** (`attest.yml`): jobs `lint` (advisory en PR, enforcing en main — política del seed), `test`, `secrets` (gitleaks-action), `gate` (`uv sync --extra attest` → `attest gate --branch $HEAD --base $BASE --description "$PR_TITLE\n$PR_BODY"` → comenta el md en el PR → sube artefactos → propaga exit code). PRs desde forks: sin secrets → `gate` corre con `--no-llm` y lo dice en el comentario (el seed ya documenta esta limitación). `doctor --strict` corre en `main` semanalmente, no en cada PR.

**CI del propio template** (ADR-003 §Action Items 6): genera con `--defaults`, instala motor mínimo del rango, corre `gate`, `doctor --compat`, `standards build --check`; y un job de upgrade vN-1 → vN sobre un repo con `domain.standards.yml` modificado, que verifica que el archivo del usuario quedó intacto.

## 8. Modelo de seguridad

**Activos:** código del usuario (el diff y los `context_files`), API keys, la integridad del veredicto.

**Fronteras de confianza:** (1) el diff es **entrada no confiable** — la escribió el autor del PR, que puede ser un fork; (2) el proveedor LLM es un tercero que ve el diff; (3) el runner de CI.

| Amenaza | Mitigación | Residual |
|---|---|---|
| Secreto en el diff llega al proveedor | Firewall gitleaks **antes** de cualquier llamada; leak = BLOCK sin transmisión; gitleaks ausente = exit 4, nunca skip | gitleaks tiene FN; documentado como "precisión ~1, recall no garantizado" |
| Exfiltración de contexto | Solo salen del repo: diff + `context_files` listados explícitamente en `[tool.attest]` + reglas `mode: llm`. Nada más. `--json` lo muestra | el usuario puede listar un archivo sensible en `context_files`; `doctor` avisa si un `context_file` coincide con patrones de secretos |
| Keys en el repo | Solo entorno; `env-secrets-only` (S1) lo vigila; `.env` en `.gitignore` por template | — |
| **Prompt injection vía el diff** (un PR que instruye al modelo "no reportes nada") | El modelo **no puede aprobar**: el veredicto lo calcula `gating.py` desde hallazgos con evidencia verificada; el peor caso de una inyección es *suprimir* hallazgos (FN), nunca fabricar un APPROVE con autoridad. Las capas 2-4 no son inyectables | FN inducido es posible; `calibrate` (P2) siembra canarios que lo detectan; el prompt v3 ya trata `<unified-diff>` como datos |
| Evasión del postfilter (paráfrasis para que la evidencia "coincida") | Matching por substring es control de calidad, **no** frontera de seguridad — así se documenta | asumido |
| Artefactos con contenido sensible | Los reportes citan líneas del diff como evidencia; un diff con secreto nunca llega a reporte (firewall) | evidencia puede citar datos no-secretos pero sensibles; los artefactos de CI heredan la retención del repo |
| PR desde fork con secrets del repo | GitHub no expone secrets a forks; el workflow degrada a `--no-llm` explícitamente | — |
| Supply chain del propio py-attest | pins con rango en el template (ADR-003), `uv.lock` en el repo del usuario, pip-audit warn-only (v1) | — |

## 9. Estrategia de pruebas

- **Unitarias** por módulo; los tests del seed migran con el código en F0 (postfilter multi-fragmento, gating, schema, secrets gate, context pack, eval metrics).
- **Contrato de proveedores** (ADR-002): suite común + fixtures grabadas; sin red en CI de PRs.
- **Regresión del golden set**: los 8 PRs del seed con respuestas del proveedor grabadas → veredictos y hallazgos esperados byte a byte; job semanal contra proveedores reales publica métricas en EVAL.md.
- **CLI**: `CliRunner` por comando, incluyendo la tabla de exit codes completa (§4.1) — cada código tiene al menos un test que lo produce.
- **Template**: los jobs cruzados de ADR-003 + quickstart cronometrado (< 15 min, PRD G1).
- **Doctor**: un fixture de repo por check en estado pass y fail.

## 10. Riesgos técnicos y qué revisar al crecer

| Riesgo | Señal | Plan |
|---|---|---|
| `ci-parity` por parsing de Makefile/workflow es frágil | falsos positivos en repos no generados por el template | v1: solo en repos con answers file; heurístico en el resto, severidad S3 |
| `no-trivial-asserts` con demasiados FP | quejas en repos con fixtures ricas | lista de allow por decorador/marker; medir en los 10 repos OSS de F2 |
| Copier cambia la semántica de `when: false`/`_skip_if_exists` | job de upgrade del template falla | pin `_min_copier_version` y rango de copier en el extra `scaffold` |
| Variancia del LLM entre proveedores desalinea la trust policy | métricas por proveedor divergen en el job semanal | política por proveedor solo si los datos lo exigen; hoy una tabla |
| Diff grande recurrente en repos reales | muchos `skipped:diff_too_large` | F2: revisar por archivo o por hunk con presupuesto; no en v1 |

## 11. Plan de implementación F0-F1 (paquetes de trabajo)

| WP | Entregable | Depende de |
|---|---|---|
| F0.1 | Esqueleto `py_attest/` + `pyproject` (hatchling, extras, click, exit codes en `main.py`) + CI del paquete | — |
| F0.2 | Migrar `gate/` desde el seed con sus tests; `Config` reemplaza rutas hardcodeadas | F0.1 |
| F0.3 | `llm/` según ADR-002 (types, policy, registry, openai portado, anthropic nuevo, contract tests) | F0.1 |
| F0.4 | `standards/` según ADR-001 (schema, registry, build, lint); `gate` resuelve severidad desde el registro | F0.2 |
| F0.5 | Golden set como fixtures grabadas + `eval/` migrado; job semanal | F0.3, F0.4 |
| F0.6 | Release `v1.0.0` a PyPI | F0.2-F0.5 |
| F1.1 | `py-attest-template` variante fastapi: copier.yml, árbol, workflows, Makefile, `core.standards.yml` inicial | F0.6 |
| F1.2 | `attest new` + `doctor --compat` (subset del catálogo: `compat-*`, `standards-*`) | F1.1 |
| F1.3 | Self-hosting: ambos repos corren `attest gate` en sus PRs | F1.1, F1.2 |
| F1.4 | Quickstart cronometrado en CI del template; docs de instalación | F1.3 |

`upgrade`, el catálogo completo del doctor y `standards new-rule` son F2, como fija el PRD.

---
*Historial: v0.1 (2026-09-01). Fuentes: PRD v0.3, ADR-001/002/003, seed `student-progress-seed` (review.py, llm.py, schema.py, postfilter.py, secrets_gate.py, context_pack.py, gating.py, Makefile, ci.yml, pyproject.toml).*
