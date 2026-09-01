# ADR-002: Interfaz de proveedor LLM

**Status:** Proposed
**Date:** 2026-09-01
**Deciders:** Luis Cruz
**Parte de:** TRD py-attest · PRD v0.3 §7.2, §11.4 · Depende de ADR-001 (los findings citan `rule_id`)

## Context

El seed (`tools/quality_gate/llm.py`, 98 líneas) habla directamente con el SDK de OpenAI: `response_format: json_schema strict`, `temperature=0` con fallback a model-default cuando el modelo lo rechaza (familia gpt-5), `max_retries=0` para tener control explícito, límite duro de 60 KB de diff que lanza error, y validación del JSON de salida hecha a mano sin dependencias. Funciona y está medido (EVAL.md), pero acopla el motor a un proveedor, y el PRD (R2) exige que el usuario elija proveedor/modelo/key, y que sin key todo lo determinista corra y el reviewer termine con mensaje claro, nunca stack trace.

Fuerzas en juego:

- **Peso en CI.** El gate corre como job de GitHub Actions en cada PR del usuario. Cada dependencia que se instala ahí cuesta segundos y superficie de fallos. Luis descartó litellm por esto (ver Trade-off Analysis: la razón correcta es peso de dependencia, no infraestructura — litellm-SDK no levanta ningún servicio).
- **Lo que realmente necesitamos es una sola operación:** "manda system prompt + contexto, devuélveme JSON que cumpla este schema". No streaming, no tools, no conversación, no embeddings.
- **Variancia y provenance.** El seed demostró que gpt-5 no acepta temperatura explícita; el artefacto de cada review estampa la temperatura aplicada. Ese contrato de provenance debe sobrevivir a la abstracción.
- **Mecanismos de salida estructurada distintos por proveedor.** OpenAI: `response_format` con JSON Schema estricto. Anthropic: la forma canónica es forzar un `tool_use` cuyo `input_schema` es el JSON Schema (`tool_choice` forzado). La abstracción tiene que absorber esa diferencia sin filtrarla al motor.
- **Testabilidad.** La suite de regresión del motor (golden set) no puede depender de la red en cada PR; los proveedores deben poder probarse con fixtures grabadas.

## Decision

Una interfaz propia y mínima en `py_attest.llm`, con los SDKs oficiales de OpenAI y Anthropic como **extras opcionales**, y una política de reintentos/timeouts que vive en el motor, no en los proveedores.

### Contrato

```python
@dataclass(frozen=True)
class ReviewRequest:
    system_prompt: str
    user_content: str            # context pack + diff, ya ensamblado por el motor
    output_schema: dict          # JSON Schema del resultado (findings con rule_id, ADR-001)
    model: str
    temperature: float | None    # None = model-default

@dataclass(frozen=True)
class ReviewResponse:
    raw_json: str                # exactamente lo que devolvió el modelo, sin tocar
    model: str                   # modelo efectivamente usado (el proveedor puede resolver alias)
    temperature_applied: str     # "0" | "model-default"  → se estampa en el artefacto
    usage: Usage | None          # tokens in/out, para costo en el reporte

class Provider(Protocol):
    name: str                    # "openai" | "anthropic" | ...
    def complete_structured(self, request: ReviewRequest) -> ReviewResponse: ...
```

**Qué hace un proveedor:** transporte, auth desde variable de entorno (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), traducir `output_schema` al mecanismo nativo de salida estructurada, aplicar el fallback de temperatura y reportar cuál quedó, y **mapear toda excepción del SDK a la taxonomía de py-attest** — nunca deja escapar una excepción cruda del SDK.

**Qué NO hace un proveedor:** validar el schema (lo hace el motor, una sola vez, sobre `raw_json`), postfiltrar evidencia, decidir veredictos, reintentar. Con esto un proveedor cabe en ~80-120 líneas, como ya demostró el seed.

### Taxonomía de errores (todas heredan de `LLMReviewError`)

| Excepción | Cuándo | Comportamiento del motor |
|---|---|---|
| `ProviderNotConfigured` | falta key, extra no instalado, proveedor desconocido | Mensaje de una línea con qué falta; las capas deterministas ya corrieron; exit 0 con veredicto `COMMENT: AI review skipped (reason)` — cumple R2 |
| `ProviderTransient` | 429, 5xx, timeout de red | Reintenta según política (abajo) |
| `ProviderRejected` | 4xx no transitorio (request inválido, modelo inexistente) | Falla visible, sin reintento |
| `StructuredOutputInvalid` | `raw_json` no parsea o no cumple schema | Un reintento; si vuelve a fallar, falla visible con el raw guardado en el artefacto |

### Política de reintentos y timeouts (en el motor)

- Timeout por llamada: 120 s (un diff ≤ 60 KB cabe con margen).
- `ProviderTransient`: máximo 2 intentos adicionales con backoff 2 s / 6 s. `StructuredOutputInvalid`: 1 reintento. Todo lo demás: ninguno.
- Los SDKs se instancian con sus reintentos internos desactivados (`max_retries=0`, como el seed) para que el número de intentos sea **nuestro** y quede estampado en el artefacto (`attempts: 2`).
- Diff mayor a `max_diff_bytes` (default 60 KB, configurable en `[tool.attest]`): el motor **no llama al proveedor** y emite `COMMENT: diff too large for AI review` (PRD R6). No es error.

### Selección y configuración

```toml
[tool.attest]
provider = "openai"          # "openai" | "anthropic"
model = "gpt-5-mini"          # string opaco, se pasa tal cual
max_diff_bytes = 61440
```

Overrides por entorno para CI: `ATTEST_PROVIDER`, `ATTEST_MODEL`. La key **solo** por entorno, nunca en config (PRD §11.7).

Registro de proveedores por **entry points** (`py_attest.providers`): los dos built-in se registran igual que lo haría un tercero. Así `py-attest[litellm]` puede existir el día que alguien lo pida como un proveedor más, sin tocar el motor — y sin imponérselo a nadie.

### Instalación

`pip install py-attest` no instala ningún SDK de LLM: las capas deterministas (`doctor`, `gate` sin IA, `lint-standards`) quedan ligeras. `py-attest[openai]`, `py-attest[anthropic]`, `py-attest[all]`. El template genera el extra que corresponde a la respuesta de Copier sobre proveedor (gate IA on por default, PRD §9.2).

## Options Considered

### Option A: litellm como capa de abstracción

| Dimensión | Evaluación |
|---|---|
| Complejidad de código propio | Muy baja — una llamada |
| Peso de dependencia | Alto — árbol transitivo grande, releases muy frecuentes, superficie enorme para una sola operación |
| Salida estructurada | Desigual entre proveedores; la traducción a `tool_use` para Anthropic no siempre es la que uno quiere |
| Control de provenance | Bajo — el fallback de temperatura y los reintentos quedan dentro de litellm, no en nuestro artefacto |

**Pros:** cien proveedores gratis.
**Contras:** pagamos en cada job de CI de cada usuario por proveedores que nadie usa; perdemos el control fino que hace al gate auditable (attempts, temperature_applied). Queda como proveedor opcional vía entry point, no como base.

### Option B: Protocol propio + SDKs oficiales como extras — **elegida**

| Dimensión | Evaluación |
|---|---|
| Complejidad | Media-baja — ~100 líneas por proveedor, ya existe una para OpenAI |
| Peso | Cero en la instalación base; un SDK en el extra elegido |
| Salida estructurada | Cada proveedor usa su mecanismo nativo, el mejor disponible |
| Control de provenance | Total — todo lo que se estampa lo decidimos nosotros |

**Pros:** cumple R2 por construcción; testeable con fixtures; extensible por terceros sin tocar el motor.
**Contras:** cada proveedor nuevo es trabajo nuestro (mitigado: entry points permiten que lo haga la comunidad); dos SDKs que mantener al día.

### Option C: Protocol propio + `httpx` crudo, sin SDKs

| Dimensión | Evaluación |
|---|---|
| Complejidad | Media-alta — reimplementar auth, errores, formatos de respuesta de cada API |
| Peso | El más bajo posible |
| Riesgo | Alto — los SDKs absorben cambios de API que nosotros tendríamos que perseguir |

**Pros:** instalación mínima incluso con IA activada.
**Contras:** duplicamos la taxonomía de errores que los SDKs ya mantienen; ganancia de peso marginal frente a Option B (los SDKs modernos son razonables) a cambio de deuda permanente.

### Option D: Framework de salida estructurada (instructor, pydantic-ai)

**Contras decisivos:** añaden una dependencia y una capa de magia para hacer lo que hacen 20 líneas con `response_format`/`tool_use`; el seed ya validó que no hace falta. Descartada.

## Trade-off Analysis

La tensión real es **control vs. cobertura de proveedores**. Un gate cuyo argumento de venta es "sus números están publicados y cada artefacto se describe a sí mismo" necesita ser dueño de cada variable que afecta el resultado: intentos, temperatura aplicada, modelo efectivo, tokens. litellm oculta justamente eso a cambio de cobertura que en v1 no necesitamos. Option B paga ~200 líneas propias (dos proveedores) por control total y una instalación base sin SDKs — y los entry points hacen que "cobertura" sea un problema que la comunidad puede resolver después sin reabrir este ADR. La restricción de temperatura de gpt-5 es el ejemplo perfecto de por qué importa: en el seed fue un `except BadRequestError` específico de OpenAI; aquí se vuelve parte del contrato (`temperature_applied`) que todo proveedor debe cumplir.

## Consequences

- **Más fácil:** cumplir R2 (sin key → mensaje claro, deterministas intactas) es una rama de código, no un caso especial; añadir un proveedor es un módulo de ~100 líneas más una suite de contrato; la instalación base sigue ligera para `doctor` y CI sin IA; todo lo que afecta al veredicto queda estampado en el artefacto.
- **Más difícil:** mantener dos SDKs al día (mitigado: pins con rango y un job semanal que corre el golden set contra proveedores reales, fuera del CI de PRs); cada proveedor necesita fixtures grabadas y mantenidas.
- **A revisar:** si aparece demanda real por un tercer proveedor (Gemini, modelos locales vía Ollama/OpenAI-compatible) — el caso "endpoint OpenAI-compatible con `base_url` configurable" probablemente cubra la mayoría sin un proveedor nuevo; considerar exponer `base_url` en `[tool.attest]` en F2.

## Action Items

1. [ ] Definir `ReviewRequest`, `ReviewResponse`, `Provider` (Protocol) y la taxonomía de errores en `py_attest/llm/`.
2. [ ] Portar el wrapper OpenAI del seed al contrato (extraer el fallback de temperatura a la forma `temperature_applied`; mapear excepciones del SDK a la taxonomía).
3. [ ] Implementar proveedor Anthropic: `tool_use` forzado con `input_schema = output_schema`; mismo mapeo de errores y temperatura.
4. [ ] Registrar ambos por entry point `py_attest.providers`; extras `[openai]`, `[anthropic]`, `[all]` en `pyproject.toml`.
5. [ ] Política de reintentos/timeouts en el motor, con `attempts` estampado en el artefacto; SDKs con reintentos internos desactivados.
6. [ ] Suite de contrato `ProviderContractTests` que todo proveedor debe pasar (raw JSON intacto, fallback de temperatura reportado, errores mapeados, nunca excepción cruda del SDK) + fixtures grabadas por proveedor.
7. [ ] `max_diff_bytes` en `[tool.attest]`; diff excedido → `COMMENT` sin llamada, no error.
8. [ ] Job semanal (no por PR) que corre el golden set contra OpenAI y Anthropic reales y publica métricas por proveedor en EVAL.md.
