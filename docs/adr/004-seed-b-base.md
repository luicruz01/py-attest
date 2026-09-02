# ADR-004: Seed A como base de código, rescates de Seed B, y gate en dos etapas

**Status:** Proposed
**Date:** 2026-09-02 (reemplaza la versión del 2026-09-01, que tenía el timeline de los seeds invertido)
**Deciders:** Luis Cruz
**Parte de:** TRD py-attest · Amends ADR-001 (catálogo), ADR-002 (proveedor), TRD v0.1 §3.1, §4.1, §5, §7, §8

## Context

El repo `student-progress-seed` (`/Users/luicruz/Documents/Personal/Code/student-progress-seed`) contiene dos implementaciones del quality gate del ejercicio Open English, en dos linajes de git que parten del mismo base (`fbd4e09`) y nunca se mezclaron:

| | **Seed B** — rama `fix/quality-gate-safety` (51840fa, 9 ago 2026); paquete `quality_gate/` | **Seed A** — `main` = `origin/main` (b397751, 12 ago 2026); `tools/quality_gate/`. **Entrega final** |
|---|---|---|
| Filosofía | Fail-closed: cualquier inconsistencia invalida la respuesta completa; tercer estado `inconclusive` | Degrade-not-drop: un hallazgo con evidencia no verificable sobrevive a `confidence=low`, visible |
| Egress al proveedor | Minimización agresiva (alias de rutas, sin literales/valores/prosa, validación residual `MINIMIZED_PATCH_V2`) | Diff crudo tras gitleaks + `context_files` |
| Catálogo de reglas | `review_rules.json` como autoridad local de severidad, con `evidence_required`/`non_examples` y severidad contextual | Implícito en el prompt v3; IDs en texto |
| Proveedor | `providers/base.py` (Protocol, `ProviderRequest/Response`) + `fake` offline + OpenAI Responses API (`store=False`) | Cliente OpenAI directo; fallback de temperatura para gpt-5 |
| Hallazgos | `side: old|new`, rangos verificados, fingerprint local | `file:line` |
| Forks en CI | Los revisa con secrets vía `pull_request_target` **sin ejecutar código del PR** (checkout del SHA base, head como objetos inertes) + tests de seguridad del workflow | `pull_request`: los forks no reciben secrets → no se revisan con IA; se documenta como limitación |
| Exit codes | 0 approve · 1 request_changes · 2 inconclusive/error | 0 approve/comment · 2 block/error |
| Eval | Corrida ciega sellada: 50% precisión, 41.67% recall, 36% recall bloqueante, una aprobación insegura (atribuido a la minimización) | 8 PRs: 6/6 bloqueos, 87.5% acierto de veredicto, F1 72 strict |
| Regla de eval | Anti-leakage: el golden set no se usa para tuning; comparar exige holdout sellado | Golden set como regresión |

Luis construyó B primero, midió, y rehizo el motor como A tres días después; A es lo que entregó y lo que está publicado. Las dos políticas para forks son válidas: A no los revisa (seguro por omisión); B los revisa sin ejecutar nada (seguro por construcción, más maquinaria). El error de la versión anterior de este ADR fue tratar la política de A como defecto.

## Decision

1. **Seed A es la base de código de F0.** Se migra `tools/quality_gate/` (context_pack, secrets_gate, schema, postfilter, gating, llm, review, eval_metrics, prompts v1-v3) y `tests/quality_gate/` a `py_attest/review/`, `py_attest/llm/`, `py_attest/eval/`. El golden set de A (6/6) es el baseline del modo `raw` desde el día uno.
2. **Se rescatan de Seed B**, pieza por pieza y cada una descartable si no aporta:
   - (a) el **catálogo** con `evidence_required`, `non_examples` y **severidad contextual** → campos de `standards.yml` (ADR-001);
   - (b) el **Protocol de proveedor** con la regla "el raw nunca cruza la frontera" y el proveedor **`fake`** → ADR-002;
   - (c) el **egress `minimized`** (egress.py + redaction.py) como modo opcional;
   - (d) la **adquisición acotada de git** (límites en streaming, sin ext-diff/textconv, SHAs completos, merge-base) y `side: old|new` en los hallazgos;
   - (e) el **job `pull_request_target`** con checkout del base y head inerte, y `test_workflow_security.py`, como **opción** del template (`fork_reviews: true`).
   Se leen con `git show fix/quality-gate-safety:<ruta>` o desde un worktree `../seed-b`; nunca se mezclan ramas del seed.
3. **Egress configurable, `raw` por default** (decisión de producto, 2026-09-01): `[tool.attest] egress = "raw" | "minimized"`. `doctor` recomienda `minimized` cuando `domain.standards.yml` contiene reglas S1 de PII.
4. **El gate se parte en dos etapas** — por claridad de fronteras, no por obligación:
   - `attest check` — ejecuta código: ruff, pytest+coverage, gitleaks sobre el árbol. Siempre sin secrets.
   - `attest review` — nunca ejecuta código del repo: diff como datos → deterministic → firewall gitleaks → egress → proveedor → validación → política → reporte.
   - `attest gate` = ambos, para local y para el job `pull_request` (repos privados o sin forks).
   - Con `fork_reviews: true`, el template genera además el job `review` en `pull_request_target` con las salvaguardas de B; sin él, los forks solo reciben `check`, como en A.
5. **Exit codes** (TRD §4.1): 0 ok/approve/comment · 2 block · 3 incompatibilidad · 4 error de ejecución **o revisión incompleta** (la semántica `inconclusive` de B se adopta: un fallo técnico nunca aprueba) · 64 uso.
6. **Política de evaluación (anti-leakage de B, adoptada):** el golden set es regresión, nunca tuning — "no empeorar vs baseline sellado por modo": `raw` = EVAL de A; `minimized` = se mide en F0.5 con el prompt v3 y ese resultado es su baseline. Comparar prompts, reglas, umbrales o modelos exige un holdout nuevo sellado (F2).
7. **`standards.yml` (ADR-001) sustituye al catálogo de B como fuente** y hereda sus campos; una regla contextual produce `requires_human_classification=true` y cuenta como COMMENT, nunca BLOCK, hasta que un check determinista la resuelva.
8. **ADR-002 se alinea con la forma de B** (`ProviderRequest/Response`, `ProviderFailure(category)`), añade `temperature_applied` (de A), `usage` y `attempts`; `fake` es proveedor oficial para tests y `calibrate`.

## Options Considered

### Option A: Seed A base + rescates de B — **elegida**
**Pros:** es la entrega final y la medida; migración más corta (~1,400 líneas, 8 archivos de tests); el baseline `raw` es bueno desde el primer día; cada rescate de B se evalúa por separado y se puede descartar. **Contras:** los rescates (catálogo, egress, git acotado) son trabajo nuevo en F0.3/F0.4; hay que leer B con cuidado para no perder sus invariantes al portar.

### Option B: Seed B base + rescates de A (decisión del 2026-09-01, revertida)
**Pros:** seguridad y contratos estrictos ya integrados; tests de seguridad del workflow existentes. **Contras:** era la implementación que el propio autor descartó; migración más densa (~1,700 líneas + 13 archivos); su baseline medido es el que no queremos; deshacer una pieza de B desde dentro del núcleo es cirugía. Se descarta al corregir el timeline.

### Option C: Reescribir desde el TRD sin migrar
**Contras decisivos:** tira ~3,000 líneas probadas y dos evals; contradice "cirugía, no invención".

## Trade-off Analysis

La pregunta correcta no era "cuál es más nueva" sino **cuál produce el baseline con el que queremos vivir y cuál permite adoptar lo mejor de la otra sin cirugía**. A da un baseline defendible en el modo default y absorbe las piezas de B como módulos opcionales; B daría un núcleo más estricto cuyo baseline hay que arreglar antes de poder afirmar nada. La separación `check`/`review` y el egress configurable se mantienen porque son buenas ideas independientemente de la base; el job `pull_request_target` se vuelve opción porque es una política, no una corrección.

## Consequences

- **Más fácil:** F0.2 migra código conocido y medido; EVAL.md publica un buen baseline desde el release 1.0; la narrativa del README es "la versión medida, con privacidad extra como modo opcional también medido".
- **Más difícil:** portar de B sin perder invariantes (rangos verificados por lado, alias solo en memoria, validación residual) exige leer sus tests y traerlos con el código; dos modos de egress con su fila cada uno en EVAL.md.
- **A revisar:** si la re-medición de F0.5 muestra que `minimized` con prompt v3 recupera recall, el default puede cambiar por datos (ADR-005, no edición de este).

## Action Items

1. [ ] TRD v0.3: §3.1 mapeo desde `tools/quality_gate/` de A con los rescates de B marcados; §7 `fork_reviews` como opción; §9 tests de B solo con las piezas rescatadas; §11 F0.2 = A.
2. [ ] PRD v0.5: evidencia con timeline correcto; §7 base = A.
3. [ ] ADR-001/002: notas de enmienda ajustadas ("se rescata de B").
4. [ ] plan-cc y runbook: rutas y ramas (A = `main` del seed; B = `fix/quality-gate-safety`, leída con `git show` o worktree `../seed-b`); prompts 3, 4a, 4b, 5 reescritos.
5. [ ] Borrar `reference/seed-a/` (A ya es `main` del seed).
