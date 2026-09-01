# ADR-003: Contrato de compatibilidad paquete ↔ template

**Status:** Proposed
**Date:** 2026-09-01
**Deciders:** Luis Cruz
**Parte de:** TRD py-attest · PRD v0.3 §7.4, §11.8 · Relacionado: ADR-001 (`version:` de standards.yml), ADR-002 (extras por proveedor)

## Context

py-attest son dos artefactos con ciclos de release independientes que tienen que funcionar juntos *dentro de cada repo generado*:

- **`py-attest`** (PyPI): CLI + motor. Llega al repo del usuario por `pip install`. Cambia rápido (bugfixes del postfilter, prompts, proveedores).
- **`py-attest-template`** (git, consumido por Copier): workflows, Makefile, `core.standards.yml`, `copier.yml`. Llega al repo del usuario por `attest upgrade` (= `copier update`, 3-way merge). Cambia cuando cambia *lo que vive en el repo del usuario*.

El escenario de falla es concreto (PRD §7.4): un repo generado con template v1.4 instala py-attest 1.2. Template v1.5 cambia los workflows para llamar `attest gate --baseline`, flag que solo existe en py-attest 1.3. El usuario corre `attest upgrade`, sus workflows se actualizan, su engine no → CI truena con "unknown flag". Al revés: py-attest 2.0 cambia el schema del reporte JSON que los workflows viejos parsean → `pip install -U` rompe repos que no tocaron nada.

Restricciones que ya fijamos:

- **Dos repos** (PRD §7), por dos razones mecánicas: Copier descubre versiones del template por **git tags** (chocarían con los tags de release de PyPI en un monorepo), y `copier update` necesita el historial git del template para reconstruir la versión vieja y hacer el 3-way merge — un template empaquetado dentro del wheel no puede actualizarse (ver Option D).
- Bugfixes del motor deben llegar con `pip install -U` **sin tocar archivos del usuario** (PRD §7); por tanto el pin no puede ser exacto.
- `attest doctor` debe detectar desalineación (PRD §7.4) y el reporte de cada review debe describir la configuración que lo produjo (provenance heredada del seed).

## Decision

**El template es la única fuente que declara qué motores soporta; el motor nunca declara nada sobre el template.** El rango vive en un solo lugar, se propaga a dos, y `doctor` verifica que los tres coincidan.

### 1. Una sola declaración, en `copier.yml`

```yaml
# copier.yml (py-attest-template)
_min_copier_version: "9.0"

attest_engine_range:            # variable calculada, no se le pregunta al usuario
  when: false
  default: ">=1.3,<2"
```

Copier soporta preguntas con `when: false` como valores calculados: se recomputan desde el template en cada `update` (el template es dueño del valor) y quedan persistidos en `.copier-answers.yml` del repo generado. Es el mecanismo idiomático — no se inventa nada.

### 2. Propagación a dos lugares del repo generado

```toml
# pyproject.toml (generado y mantenido por el template)
[project.optional-dependencies]
attest = ["py-attest[openai]>=1.3,<2"]      # rango desde attest_engine_range; extra desde la respuesta de proveedor (ADR-002)
```

```yaml
# .copier-answers.yml (lo escribe Copier)
_commit: v1.5.0                  # versión del template usada
_src_path: gh:luicruz01/py-attest-template
attest_engine_range: ">=1.3,<2"
```

Los workflows generados instalan `pip install -e .[attest]` (o `uv sync --extra attest`), así que **CI siempre instala un motor dentro del rango que el template declaró**. El rango se renderiza en el pyproject con un comentario `# managed by attest upgrade`; editarlo a mano es legal pero `doctor` lo señala.

### 3. Verificación: `attest doctor` compara tres fuentes

| Comparación | Hallazgo | Acción sugerida |
|---|---|---|
| Motor en ejecución (`importlib.metadata.version("py-attest")`) fuera de `attest_engine_range` (answers) | **Desalineación motor/template** | `pip install -U "py-attest>=1.3,<2"` (comando exacto impreso) |
| Rango en `pyproject.toml` ≠ rango en `.copier-answers.yml` | **Pin editado a mano** | `attest upgrade` (re-renderiza) o reconciliar a mano |
| `_commit` en answers < último tag del template (solo con red; se omite en `--offline`) | **Template desactualizado** | `attest upgrade` disponible: v1.4.0 → v1.6.0 |
| `version:` de `core.standards.yml` (ADR-001) no soportado por el motor | **Schema de estándares incompatible** | `attest upgrade` o actualizar motor, según dirección |

Severidad en el reporte del doctor: la desalineación motor/template es **S1 del doctor** (el gate puede estar corriendo con flags que no existen; es la falla que este ADR existe para evitar); las otras tres son S2.

### 4. `attest upgrade` = `copier update` + verificación

1. `copier update` (respeta `_skip_if_exists`, 3-way merge, muestra conflictos).
2. Rerender de `attest_engine_range` → pyproject actualizado junto con los workflows, en el mismo commit.
3. `doctor --compat` sobre el resultado. Si el motor instalado quedó fuera del nuevo rango: imprime el `pip install -U ...` exacto y **sale con código 3** (no instala nada en el entorno del usuario por su cuenta — nunca). Un `upgrade` que deja el repo en estado inconsistente no puede salir con 0.

### 5. Disciplina de versiones (ambos repos taggean `vX.Y.Z`)

**Motor (`py-attest`) — SemVer sobre sus tres contratos públicos:** la CLI (comandos, flags, exit codes), el schema del reporte JSON, y el schema de `standards.yml` (`version:` de ADR-001).

| Cambio | Bump |
|---|---|
| Quitar/renombrar comando o flag; cambiar exit codes; cambio incompatible en schema de reporte o de standards.yml | **major** |
| Comando, flag, check o proveedor nuevo; campo nuevo opcional en schemas | minor |
| Fixes de postfilter, prompts, proveedores; sin cambio de contrato | patch |

**Template (`py-attest-template`):**

| Cambio | Bump |
|---|---|
| `attest_engine_range` sube su cota superior (requiere nuevo major del motor) | **major** |
| Sube la cota inferior (requiere feature nueva del motor, mismo major); archivos nuevos; reglas nuevas en el núcleo | minor |
| Fixes en workflows/Makefile sin exigir motor más nuevo | patch |

Regla operativa: **un cambio de template que usa un flag nuevo del motor sube `attest_engine_range` en el mismo PR**, y el CI del template lo verifica generando un repo, instalando el motor mínimo del rango y corriendo `attest gate` en él (ver Action Items).

### 6. Provenance en cada artefacto

Cada reporte de `attest gate` estampa `engine_version`, `template_version` (`_commit` de answers, si el repo fue generado), `standards_schema_version`, junto con lo que ya estampaba el seed (prompt, modelo, temperatura, intentos). Cualquier review es reproducible o al menos diagnosticable desde su propio JSON.

## Options Considered

### Option A: Sin contrato explícito — "usar siempre la última de ambas"

| Dimensión | Evaluación |
|---|---|
| Complejidad | Nula |
| Riesgo | Alto — el escenario de falla del Context ocurre en silencio, en CI, en repos de terceros |
| Diagnóstico | Ninguno — el error aparece como "unknown flag" sin pista de la causa |

**Contras decisivos:** es exactamente el estado de cosas que el PRD identifica como problema; con un solo usuario funciona por disciplina, con diez no.

### Option B: Rango declarado en el template, propagado y verificado — **elegida**

| Dimensión | Evaluación |
|---|---|
| Complejidad | Baja — una variable calculada de Copier, una comparación en doctor |
| Riesgo | Bajo — la desalineación se detecta antes de que rompa, con el comando de remedio impreso |
| Precedentes | `_min_copier_version` de Copier; pre-commit `minimum_pre_commit_version`; GitHub Actions `uses: x@v4` |

**Pros:** un solo lugar de verdad; los bugfixes del motor siguen llegando por pip sin tocar el repo; upgrade y doctor cierran el ciclo. **Contras:** el usuario que edita el pin a mano puede crear inconsistencia — detectada, no prevenida.

### Option C: Pin exacto gestionado por `upgrade` (estilo lockfile)

| Dimensión | Evaluación |
|---|---|
| Reproducibilidad | Máxima |
| Fricción | Alta — cada patch del motor exige un `attest upgrade` y un commit en cada repo |

**Contras decisivos:** viola la decisión del PRD de que los bugfixes lleguen por `pip install -U` sin tocar archivos; multiplica PRs de mantenimiento en cada repo generado por cada patch. La reproducibilidad exacta ya la da el lockfile del propio proyecto del usuario (`uv.lock`), no hace falta duplicarla.

### Option D: Template empaquetado dentro del wheel (versión única, lockstep)

| Dimensión | Evaluación |
|---|---|
| Compatibilidad | Trivial — una sola versión |
| `attest upgrade` | **Roto** — `copier update` reconstruye la versión anterior del template desde su historial git para el 3-way merge; un directorio dentro de site-packages no tiene historial |
| Cadencia | Cada cambio de workflow exige release a PyPI |

**Contras decisivos:** elimina la característica que distingue a Copier de Cookiecutter (actualización con merge) — es decir, reintroduce el problema #1 del PRD ("los templates envejecen"). Se documenta porque es la objeción natural ("¿por qué no un solo paquete?") y conviene que la respuesta esté escrita.

## Trade-off Analysis

La pregunta de fondo es **quién es dueño del acoplamiento**. Los archivos que viven en el repo del usuario (workflows) son los que invocan al motor; por tanto quien los genera — el template — es quien sabe qué motor necesitan. Ponerlo en el motor invertiría la dependencia (el motor tendría que conocer todas las versiones de template que existen). Option B sigue esa flecha y usa mecanismos que ya existen en Copier y pip, así que el costo de implementación es pequeño y el costo de mantenimiento es una regla de disciplina ("sube el rango en el mismo PR") respaldada por un test de CI. Option C compra reproducibilidad que el lockfile del usuario ya provee, a cambio de fricción constante; Option D compra simplicidad a cambio de la característica central del producto.

## Consequences

- **Más fácil:** el escenario de falla del Context se vuelve un hallazgo S1 del doctor con comando de remedio, en vez de un error críptico en CI; cada artefacto de review dice exactamente con qué motor y template se produjo; el CI del template prueba la compatibilidad mínima automáticamente.
- **Más difícil:** disciplina de bumps — un cambio de template que olvida subir el rango pasa desapercibido hasta que el test de "motor mínimo del rango" falla (por eso ese test es obligatorio, no opcional); `doctor` necesita red para el check de "template desactualizado" (se degrada limpio en `--offline`).
- **A revisar:** cuando existan varios núcleos de estándar (PRD P2), el `version:` de `standards.yml` probablemente necesite su propio rango independiente del motor; hoy se acopla al major del motor y eso basta.

## Action Items

1. [ ] `attest_engine_range` como variable calculada (`when: false`) en `copier.yml`; renderizarla en el `pyproject.toml` generado bajo `[project.optional-dependencies].attest` con el extra de proveedor (ADR-002).
2. [ ] Workflows generados instalan siempre vía `.[attest]` (nunca `pip install py-attest` suelto).
3. [ ] `attest doctor`: las cuatro comparaciones de la tabla §3, con severidades y comando de remedio impreso; flag `--offline` que omite la consulta de tags.
4. [ ] `attest upgrade`: `copier update` → rerender → `doctor --compat`; exit 3 si el motor instalado queda fuera del rango nuevo; nunca instala paquetes por su cuenta.
5. [ ] Provenance: `engine_version`, `template_version`, `standards_schema_version` en el JSON y el markdown de cada review.
6. [ ] CI de `py-attest-template`: job que genera un repo desde el template, instala **la versión mínima** de `attest_engine_range` y corre `attest gate` + `attest doctor --compat` sobre él; falla si algún comando/flag no existe.
7. [ ] CI de `py-attest`: job que genera un repo con el **último tag del template** y corre el gate con el motor de la rama, para detectar rupturas del lado del motor antes de publicar.
8. [ ] CHANGELOG de ambos repos con sección "Compatibilidad" por release (rango soportado / motor mínimo requerido).
