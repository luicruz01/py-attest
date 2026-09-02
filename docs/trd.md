# TRD v0.3 — py-attest

**Producto:** `py-attest` (paquete PyPI, import `py_attest`, comando `attest`) + `py-attest-template` (template Copier)
**Estado:** Borrador para revisión · **Autor:** Luis Cruz (con Claude) · **Fecha:** 2026-09-02
**Base:** PRD v0.5 · ADR-001 (standards.yml) · ADR-002 (proveedor LLM) · ADR-003 (compatibilidad) · **ADR-004 (Seed A como base, rescates de Seed B; gate en dos etapas)**
**Cambios vs v0.2:** la base de código vuelve a ser Seed A (`tools/quality_gate/`, la entrega final y medida); las piezas de Seed B entran como rescates (★) en F0.3/F0.4; el job `pull_request_target` pasa a ser opción del template (`fork_reviews`); se conservan la separación `check`/`review`, el egress configurable, `inconclusive` → 4 y el anti-leakage.

**Rutas de referencia (máquina de Luis):** py-attest en `/Users/luicruz/Documents/Personal/Code/py-attest`. Seed A = `../student-progress-seed` en `main` (`tools/quality_gate/`, `tests/quality_gate/`, `eval/`). Seed B = rama `fix/quality-gate-safety` del mismo repo, leída con `git show fix/quality-gate-safety:<ruta>` o desde un worktree `../seed-b` (`git worktree add ../seed-b fix/quality-gate-safety`). Nunca se mezclan ramas del seed.

---

## 1. Requisitos que gobiernan el diseño

**Funcionales** (PRD §6): R1 motor como paquete · R2 proveedor configurable y degradación limpia sin key · R3 golden set como regresión (nunca tuning) · R4 `attest new` · R5 `standards.yml` · R6 gate en dos etapas con un comodín local · R7 self-hosting · R8 `upgrade` · R9 `doctor`.

**No funcionales:**

| Requisito | Valor | Origen |
|---|---|---|
| **`attest review` nunca ejecuta código del repo revisado** | no invoca pytest/ruff/hooks/imports; adquiere el diff como datos. Es lo que permite el job `pull_request_target` opcional (`fork_reviews`) | ADR-004 §4, Seed B ADR-003 |
| Instalación en CI ligera | base sin SDKs de LLM ni Copier; extras por uso | ADR-002 |
| Paridad local/CI | `make gate` = `attest check` + `attest review`; los workflows llaman los mismos comandos | PRD G1 |
| Determinismo | mismo diff + misma config → mismo veredicto salvo la capa LLM, acotada por la trust policy | Seed A EVAL |
| Fail-closed | un fallo técnico nunca se convierte en aprobación (exit 4, check rojo, humano) | Seed B |
| Sin telemetría | ninguna llamada de red fuera del proveedor elegido o git/PyPI/GitHub por acción explícita | PRD non-goal |
| Python | 3.11 – 3.13 | seed |
| Tiempo | `check` ≤ 3 min en repo pequeño; `review` acotado por límites de patch (bytes/archivos/líneas) y timeouts de git/proveedor | Seed B |
| Offline | `check` completo; `review --provider fake`; `doctor --offline` | R2 |

## 2. Arquitectura de alto nivel

```
 repo del usuario (generado o existente)
 ┌──────────────────────────────────────────────────────────────────────┐
 │ pyproject [tool.attest]  core/domain.standards.yml  TEAM-STANDARDS.md │
 │ Makefile: gate = check + review                                       │
 │ .github/workflows/attest.yml                                          │
 │   job "check"  (pull_request, sin secrets, ejecuta el commit del PR)  │
 │   job "review" (pull_request, secrets del repo; forks: skip)           │
 │   [fork_reviews] job "review" en pull_request_target: checkout del    │
 │                 SHA base, head como objetos inertes (Seed B)          │
 └───────────┬───────────────────────────────┬──────────────────────────┘
             ▼                               ▼
 ┌──── attest check ────┐        ┌──────── attest review ───────────────┐
 │ ruff · pytest+cov ·  │        │ diff acotado (git como datos)        │
 │ gitleaks (árbol)     │        │ → deterministic (secretos, TODOs)    │
 │ exit 0/2/4           │        │ → firewall: secreto ⇒ BLOCK, sin LLM │
 └──────────────────────┘        │ → egress raw | minimized            │
                                 │ → provider (fake|openai|anthropic)  │
                                 │ → validación cerrada (schema, rule_id│
                                 │   ∈ registry, rangos en líneas       │
                                 │   cambiadas, severidad = catálogo)   │
                                 │ → evidence_policy fail_closed|degrade│
                                 │ → policy (tabla) → report (md/json)  │
                                 │ exit 0/2/3/4                         │
                                 └──────────────────────────────────────┘
 attest gate (local) = check ; review        attest doctor = catálogo §6
```

## 3. Diseño del paquete `py-attest`

### 3.1 Layout de módulos (mapeo desde Seed A; rescates de Seed B marcados ★)

```
py_attest/
├── cli/                     click; main.py mapea excepciones → exit codes (§4.1)
│   ├── check.py review.py gate.py doctor.py new.py upgrade.py standards.py calibrate.py
├── config.py                [tool.attest] + [tool.attest.limits] + ATTEST_*
├── standards/               ADR-001 (+ evidence_required, non_examples, severity_policy ★)
│   ├── schema.json registry.py build.py lint.py
│   └── migrate_review_rules.py   ★ B review_rules.json → core/domain.standards.yml (fixture de migración)
├── check/                   NUEVO: las capas que ejecutan código
│   └── runner.py            ruff, pytest+cov, gitleaks sobre el árbol → hallazgos deterministic     ← A Makefile/ci.yml
├── review/                  ← A tools/quality_gate/ (el núcleo)
│   ├── diff.py              git diff base...head como datos                                      ← A review.py (_branch_diff)
│   │                        ★ límites en streaming, SHAs completos, merge-base, --full-index      ← B diff.py
│   ├── models.py            Finding(rule_id, side ★, …), ReviewResult(schema_version)             ← A schema.py + ★ B models.py
│   ├── deterministic.py     ★ secretos de alta confianza en líneas añadidas, TODOs sin ticket       ← B deterministic.py
│   ├── secrets_gate.py      gitleaks sobre el diff por stdin, --redact (firewall)                ← A secrets_gate.py
│   ├── context_pack.py      referencias (context_files) + reglas mode:llm + diff, como datos      ← A context_pack.py
│   ├── egress/raw.py        context pack (default)                                               ← A
│   ├── egress/minimized.py  ★ alias de rutas, eliminación de valores, validación residual         ← B egress.py + redaction.py
│   ├── reviewer.py          orquesta egress → provider → validación                              ← A review.py (main) + llm.py (parte)
│   ├── postfilter.py        evidencia por fragmentos, degrade-not-drop (evidence_policy=degrade)  ← A postfilter.py
│   ├── validation.py        ★ fail_closed: rangos en líneas cambiadas por lado, alias, severidad  ← B reviewer.py (validación)
│   ├── policy.py            TRUST_POLICY (severidad × confianza) + contextual → COMMENT           ← A gating.py + ★ B policy.py
│   ├── report.py            JSON (§4.3) + Markdown; sanitización de salida                       ← A review.py (render) + ★ B report.py
│   └── github_comment.py    ★ comentario idempotente con marcador                                 ← B github_comment.py
├── llm/                     ADR-002
│   ├── types.py             ★ forma de B providers/base.py + temperature_applied (A), usage, attempts
│   ├── policy.py registry.py
│   ├── prompts/reviewer_v3.md (A) · code_review_v2.txt (★ B, para egress minimized)
│   └── providers/openai.py (A llm.py: json_schema strict + fallback de temperatura; ★ store=False de B)
│                 fake.py (★ B) · anthropic.py (nuevo)
├── doctor/                  runner.py checks/ report.py (§6)
└── eval/                    ← A eval_metrics.py + golden set (fixtures grabadas); ★ B scoring policy (severity-exact)
```

Principio: el código de A se mueve casi intacto a `review/` y `llm/`; cada ★ es un módulo o campo que se porta desde `fix/quality-gate-safety` **junto con sus tests** (`test_egress.py`, `test_diff.py`, `test_contracts.py`, `test_rule_catalog.py`, `test_workflow_security.py` → template), y se puede descartar si no aporta. Los 8 archivos de tests de A (`tests/quality_gate/`) migran en F0.2 y son la red de seguridad.

### 3.2 Toolchain y dependencias

Sin cambios respecto a v0.1 (hatchling + hatch-vcs, uv, click, tomllib, pyyaml, jsonschema, jinja2), más `packaging` (rangos SemVer en doctor). `pydantic` solo si el rescate de `models.py` de B lo justifica (A valida a mano sin dependencias); decidir en F0.4 y anotarlo en el PR. Extras: base · `scaffold` (copier) · `openai` · `anthropic` · `all`. `fake` no necesita extra.

### 3.3 Configuración (`[tool.attest]`)

```toml
[tool.attest]
provider = "openai"                  # fake | openai | anthropic
model = "gpt-5-mini"
egress = "raw"                       # raw | minimized        (ADR-004 §3)
evidence_policy = "degrade"          # degrade (A, default: es lo medido) | fail_closed (★ B)
base_branch = "main"
context_files = []                   # solo se usan con egress = "raw"; doctor avisa si parecen sensibles
standards = { core = "core.standards.yml", domain = "domain.standards.yml", output = "TEAM-STANDARDS.md" }
reports_dir = "reports/"

[tool.attest.limits]                 # ★ de B: la adquisición se aborta al primer byte por encima
max_patch_bytes = 1_000_000
max_files = 200
max_added_lines = 10_000
max_line_length = 10_000
git_timeout = 15.0
provider_timeout = 30.0
```

Overrides: `ATTEST_PROVIDER`, `ATTEST_MODEL`, `ATTEST_EGRESS`, `ATTEST_BASE_BRANCH`. Keys solo por entorno. Claves desconocidas → 64.

## 4. Contratos de la CLI

### 4.1 Exit codes

| Código | Significado | Equivalencia Seed B |
|---|---|---|
| 0 | OK · `APPROVE` · `COMMENT` | `approve` (0) |
| 2 | **BLOCK** (`request_changes`); doctor `--strict` con S1 | `request_changes` (1) |
| 3 | Incompatibilidad motor↔template (ADR-003) | — |
| 4 | **Error de ejecución o revisión incompleta** (`inconclusive` ★): proveedor, git, límites excedidos, patch binario/no representable, gitleaks ausente, schema inválido tras reintento. **El check falla; nunca aprueba.** | `inconclusive` (2) |
| 64 | Error de uso | — |

Click devuelve 2 en errores de uso: `main.py` los captura → 64.

### 4.2 Comandos

**`attest check`** — `[path]` · `--no-tests` · `--no-lint` · `--json`. Ejecuta ruff, pytest+coverage y gitleaks sobre el árbol de trabajo; produce hallazgos `deterministic` con `rule_id` del núcleo (`testing-1`, `secrets-1`, `code-quality-*`). **Es el único comando que ejecuta código del repo.** Exit 0/2/4/64.

**`attest review`** — `--branch <ref>` · `--base <ref>` (A) o `--head <sha>` (★ B, para CI con SHAs) · `--diff-file` (fixtures) · `--provider fake|openai|anthropic` · `--fake-response <json>` ★ · `--egress raw|minimized` · `--description` (no confiable: redactado, acotado, delimitado como datos) · `--out <dir>` · `--json` · `--prompt-version` · límites como flags que sobreescriben `[tool.attest.limits]` ★. **No ejecuta código del repo**: git como datos (`--no-ext-diff`, argumentos como lista; ★ `--no-textconv --full-index`, entorno limpio, límites en streaming). Exit 0/2/3/4/64.

**`attest gate`** — `--branch <ref>` · `--base` · `--out` · `--no-llm`. Comodidad local y para repos privados sin forks: ejecuta `check` y luego `review` sobre `base...branch`, combina hallazgos y emite un solo reporte. Exit = máximo de ambos.

**`attest doctor`**, **`attest standards build|lint|new-rule`**, **`attest new`**, **`attest upgrade`**, **`attest calibrate`**: sin cambios respecto a v0.1 §4.2, salvo `calibrate` que en v1 usa `--provider fake` para verificar el pipeline sin key.

### 4.3 Schema del reporte (JSON, `schema_version: 3`)

```jsonc
{
  "schema_version": 3,
  "verdict": "BLOCK",                          // APPROVE | COMMENT | BLOCK | INCONCLUSIVE
  "exit_code": 2,
  "stage": "review",                           // check | review | gate
  "source": {"base_sha": "…", "head_sha": "…", "merge_base_sha": "…", "patch_sha256": "…"},
  "review_complete": true,                     // false ⇒ INCONCLUSIVE (B): límites, binario, deleción no resuelta…
  "layers": {"deterministic": "ran", "secrets": "pass",
             "llm": "ran" | "skipped:no_provider_key" | "skipped:secret_detected" | "skipped:limits_exceeded" | "skipped:--no-llm"},
  "egress": {"mode": "raw", "context_files": ["app/models.py"]} | {"mode": "minimized", "payload_version": "MINIMIZED_PATCH_V2"},
  "findings": [{
    "rule_id": "testing-2", "severity": "S2",  // severidad = catálogo (fija) …
    "requires_human_classification": false,    // … o true si la regla es contextual (severity_policy) ⇒ COMMENT
    "confidence": "high", "evidence_verified": true,
    "path": "app/streaks.py", "side": "new", "line_start": 10, "line_end": 10,
    "title": "…", "evidence": "…", "explanation": "…", "suggested_fix": "…", "fingerprint": "…"
  }],
  "filtered_out": [{"reason": "range_not_in_changed_lines", "finding": {…}}],   // solo con evidence_policy=degrade; con fail_closed la respuesta entera se invalida (INCONCLUSIVE)
  "summary": "…",
  "meta": {"engine_version": "…", "template_version": "…", "standards_schema_version": 1,
           "prompt_version": "v3", "provider": "openai", "model": "…", "temperature_applied": "…", "attempts": 1,
           "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}, "estimated_cost_usd": "0.0000",
           "gate_commit": "…", "generated_at": "…"}
}
```

Nunca se incluyen: el patch original, la respuesta cruda del proveedor, el mapa de alias, prompts, stack traces (B). `ReviewResult.from_json` lee `schema_version` 1.0/2.0 de B para el eval histórico; siempre escribe 3.

### 4.4 Schema del doctor — sin cambios (v0.1 §4.4).

## 5. Pipeline en dos etapas — detalle y degradaciones

**`attest check`** (ejecuta código; job sin secrets):

| # | Capa | Falla → |
|---|---|---|
| 1 | ruff check + format --check | S3 → COMMENT, nunca BLOCK |
| 2 | pytest + coverage `fail_under` | BLOCK con `testing-1` |
| 3 | gitleaks sobre el árbol | BLOCK con `secrets-1` |

**`attest review`** (no ejecuta código; job con secrets):

| # | Capa | Implementación | Falla → |
|---|---|---|---|
| 1 | Adquisición | A `git diff base...branch --no-ext-diff`; ★ B: SHAs completos, merge-base, límites en streaming, `--no-textconv --full-index` | ref inválida / ★ límite excedido / binario → **INCONCLUSIVE (4)**, sin proveedor |
| 2 | Deterministic ★ | B: secretos de alta confianza en líneas añadidas, TODOs sin ticket | secreto → BLOCK, **sin proveedor**, material no copiado a evidencia |
| 3 | Firewall gitleaks (diff) | A `secrets_gate.py` por stdin, `--redact` | leak → BLOCK sin proveedor; gitleaks ausente → 4 |
| 4 | Egress | `raw` (default): context pack de A · `minimized` ★: B egress con validación residual | `minimized` residual falla → INCONCLUSIVE (4); nunca se envía ni se hace eco del valor |
| 5 | Proveedor | ADR-002; `fake` para tests/calibrate | sin key → `skipped:no_provider_key`, veredicto por capas 2-3 (exit 0/2); transitorio → reintentos; permanente → 4 |
| 6 | Validación | schema (A) + `rule_id ∈ registry` (ADR-001) + ★ rangos dentro de líneas cambiadas del lado declarado + severidad desde el catálogo o contextual ⇒ `requires_human_classification` | `degrade` (default, A): `rule_id` desconocido o rango fuera de las líneas cambiadas → `filtered_out` con `reason` (visible, binario); hallazgos válidos conservan la severidad resuelta del catálogo · `fail_closed` ★: cualquier fallo invalida la respuesta entera → INCONCLUSIVE |
| 7 | Policy | `TRUST_POLICY[(severity, confidence)]`; contextual → COMMENT; `review_complete=false` → INCONCLUSIVE aunque no haya hallazgos | — |
| 8 | Reporte | JSON + md sanitizados; comentario idempotente en PR (B) | IO → 4 |

Aprobación (exit 0 con `APPROVE`) requiere, como en B: adquisición completa, sin límites excedidos, sin binario/deleción no resuelta, proveedor exitoso (o explícitamente omitido sin key/`--no-llm`, y entonces el reporte lo dice), respuesta íntegramente válida y sin S1/S2.

## 6. Catálogo v1 de checks del doctor

Sin cambios respecto a v0.1 §6, con tres adiciones: `egress-mode-advised` (S3: recomienda `minimized` si `domain.standards.yml` tiene reglas S1 de PII y `egress = raw`), `context-files-sensitive` (S2: un `context_file` coincide con patrones de secretos/PII), `workflow-boundaries` (S1: el workflow generado no ejecuta código en el job `pull_request_target` — reutiliza los asserts de B `test_workflow_security.py`).

## 7. Template `py-attest-template`

`copier.yml` como v0.1 §7 más `egress: {choices: [raw, minimized], default: raw}` y `fork_reviews: {type: bool, default: false, help: "Review PRs from forks with pull_request_target (never executes PR code)"}`.

**Workflow generado (`attest.yml`):**

| Job | Evento | Permisos | Qué hace |
|---|---|---|---|
| `check` | `pull_request`, `push: main` | `contents: read`, sin secrets | checkout del commit del evento; `uv sync`; `attest check`; sube JSON |
| `review` (default, como A) | `pull_request` | `contents: read`, `pull-requests: write`; `OPENAI_API_KEY` solo en el paso `attest review` | `attest review --branch $HEAD --base $BASE`; comenta con marcador; propaga exit code. **PRs de forks:** sin secrets → `--no-llm`, y el comentario lo dice (limitación documentada de A) |
| `review` (con `fork_reviews: true` ★, como B) | `pull_request_target` (`opened`, `synchronize`, `ready_for_review`; drafts omitidos) | `contents: read`, `pull-requests: write`; key solo en el paso `attest review` | checkout de `base.sha` sin credenciales persistidas, sin submódulos/LFS; `head.sha` validado (40 hex) y fetcheado con `--no-tags --no-recurse-submodules` como objetos inertes; **nunca checkout ni ejecución del head**; `attest review --head $HEAD_SHA --base $BASE_SHA` |

Acciones pineadas por SHA, timeouts y concurrency en todos los jobs; sin cache en el privilegiado. Branch protection: `check` y `review` requeridos. Makefile: `gate` = `attest gate` (local, un solo comando). Con `fork_reviews: true` el CI del template corre los asserts de seguridad del workflow (★ `test_workflow_security.py` de B) contra el workflow **renderizado**.

## 8. Modelo de seguridad

Hereda v0.1 §8 y añade lo que se rescata de B (★):

| Amenaza | Mitigación |
|---|---|
| **Ejecución de código del PR con secrets en el entorno** (forks) | Default (A): los forks no reciben secrets → sin revisión IA, explícito en el comentario. Con `fork_reviews` ★: `review` no ejecuta nada del repo; el job privilegiado hace checkout del SHA base y trata el head como datos; `workflow-boundaries` del doctor y los tests de seguridad del template lo verifican |
| Exfiltración vía diff | `raw`: firewall gitleaks + deterministic + `context_files` explícitos y auditados por doctor · `minimized`: alias de rutas, eliminación de literales/valores/prosa, validación residual fail-closed, mapa de alias solo en memoria |
| Prompt injection vía diff/título/cuerpo | título y cuerpo redactados, acotados, delimitados como datos; el modelo no puede aprobar (policy por tabla); peor caso = FN; contextuales nunca bloquean por sí solas |
| Alias desconocido o rango fuera del diff en la respuesta | invalidación atómica (fail_closed) o degradación visible (degrade) — nunca silencio |
| Artefactos | nunca contienen patch original, respuesta cruda, alias, prompts, stack traces; el comentario del PR se sanitiza de forma independiente |
| Proveedor | Responses API con `store=False`, sin tools, sin `previous_response_id`; sin reclamo de ZDR (documentado como en B) |

## 9. Estrategia de pruebas

v0.1 §9 más: los 8 archivos de tests de A migran con el código en F0.2; de B se traen, **junto con cada rescate**, `test_egress.py`, `test_diff.py`, `test_contracts.py` (side/rangos), `test_rule_catalog.py`, `test_github_comment.py`, `test_anti_leakage.py` y `test_workflow_security.py` (al template). **Anti-leakage** como test: el paquete instalable no importa ni lee `eval/`; el golden set es regresión ("no empeorar vs baseline sellado por modo": `raw` = EVAL de A), y la comparación de prompts/reglas/modelos usa un holdout nuevo sellado (F2).

## 10. Riesgos técnicos

v0.1 §10 más: (a) dos modos de egress y dos políticas de evidencia — cada combinación necesita su fila en EVAL.md; (b) `pull_request_target` es delicado — si `fork_reviews` está activo, el test de seguridad del workflow es obligatorio en el CI del template; (c) portar los rescates de B sin sus invariantes (rangos por lado, alias solo en memoria, validación residual) — por eso cada rescate viaja con sus tests; (d) el default `raw` puede ser inaceptable para algunos usuarios — el doctor lo señala y el README lo explica en la primera pantalla.

## 11. Plan de implementación F0-F1

| WP | Entregable | Depende de |
|---|---|---|
| F0.1 | Esqueleto + CI + exit codes (incluye 4 = inconclusive) | — |
| F0.2 | **Migrar Seed A** `tools/quality_gate/` → `py_attest/review/` + `llm/` con sus 8 tests; `check/` nuevo (ruff/pytest/gitleaks); `attest check`, `attest review`, `attest gate`; exit codes 2/4 | F0.1 |
| F0.3 | `llm/` según ADR-002 (★ forma de B, `fake` ★, Anthropic nuevo, OpenAI de A con `store=False` ★); egress `minimized` ★ con `test_egress.py`; git acotado ★ con `test_diff.py` | F0.2 |
| F0.4 | `standards/` según ADR-001 (+ campos ★); `migrate_review_rules` ★; validación con `rule_id` y severidad de catálogo; contextuales; `side` ★ y rangos por lado con `test_contracts.py`; `evidence_policy` degrade/fail_closed | F0.2 |
| F0.5 | Golden set de A (8 patches; ★ integridad por `patch_sha256` de B) como fixtures; `expected.json`; **medición de `minimized` con prompt v3** (su baseline); EVAL.md con ambos; job semanal; anti-leakage ★ | F0.3, F0.4 |
| F0.6 | Release `v1.0.0` | todo lo anterior |
| F1.x | Como v0.1 §11 con el workflow de §7 (`fork_reviews` opcional ★) | F0.6 |

---
*Historial: v0.1 (2026-09-01) → v0.2 (2026-09-01, ADR-004 con timeline invertido) → v0.3 (2026-09-02, ADR-004 corregido: Seed A base). Fuentes: Seed A (`main`: `tools/quality_gate/*`, `tests/quality_gate/*`, `EVAL.md`, `DECISIONS.md`); Seed B (`fix/quality-gate-safety`: `quality_gate/README.md`, `models.py`, `policy.py`, `rules.py`, `providers/base.py`, `cli.py`, `EVAL.md`, `DECISIONS.md`, `eval/README.md`).*
