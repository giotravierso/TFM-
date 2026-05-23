# Política de Debida Diligencia de Reclamantes
## PEPIN-POL-CP-0006 · v.0005 · 04/04/2023
## Seguros Pepín, S.A. — Versión académica PoC Smart-Claims Agent

---

## 1. Objeto y Alcance

Esta política establece los procedimientos de **debida diligencia** que Seguros Pepín
debe aplicar sobre los reclamantes antes de proceder al pago de cualquier
indemnización, en cumplimiento de la normativa contra el Lavado de Activos y
Financiamiento del Terrorismo (LA-FT).

Aplica a toda reclamación de seguros gestionada por el departamento de Reclamaciones,
con independencia del monto o tipo de cobertura.

---

## 2. Niveles de Debida Diligencia

### 2.1 Debida Diligencia Simplificada (DDS)

Aplica a la **mayoría de reclamaciones**. Incluye los siguientes pasos:

1. **Verificación de identidad** del reclamante y del conductor (cédula de identidad vigente).
2. **Búsqueda en listas de sanciones** OFAC/ONU mediante Dow Jones Riskcenter o
   herramienta equivalente aprobada por Cumplimiento.
3. **Perfil del reclamante**: Verificación de que la actividad declarada es consistente
   con el tipo de reclamación.
4. **Registro en el expediente**: Todos los documentos de DDS se archivan en el expediente.

### 2.2 Debida Diligencia Ampliada (DDA)

Se activa automáticamente cuando se cumple al menos una de las siguientes condiciones:

| Condición | Descripción |
|-----------|-------------|
| **Sospecha de fraude** | Score de fraude > 50% calculado por el Agente G |
| **Indicios LA-FT** | Transacciones inusuales, complejas o sin propósito económico aparente |
| **Listas internacionales** | El reclamante o conductor aparece en OFAC, ONU u otras listas de sanciones |
| **Transacción inusual** | Monto, frecuencia o patrón que se desvía significativamente del perfil del cliente |
| **Decisión del Oficial** | El Oficial de Cumplimiento determina que procede DDA por otras características |

La **DDA incluye** todos los pasos de la DDS más:
- Investigación ampliada de la fuente de riqueza del reclamante
- Verificación adicional de la cadena de propiedad del vehículo
- Revisión de historial de reclamaciones anteriores (mínimo últimos 3 años)
- Entrevista con el reclamante (presencial o por videollamada)
- Informe escrito del Oficial de Cumplimiento con decisión motivada

---

## 3. Búsqueda en Listas de Sanciones (OFAC/ONU)

### 3.1 Obligatoriedad

Toda reclamación **debe** pasar por la búsqueda en listas de sanciones antes de
emitir cualquier pago. Esta búsqueda es realizada automáticamente por el **Agente G**
del sistema Smart-Claims mediante matching difuso (fuzzy matching).

### 3.2 Criterio de coincidencia

El sistema utiliza `token_sort_ratio ≥ 85` (librería rapidfuzz) para detectar
coincidencias, tolerando variaciones ortográficas, orden de apellidos y errores
tipográficos comunes.

### 3.3 Procedimiento en caso de coincidencia

Si el Agente G detecta una coincidencia en listas de sanciones:

1. La reclamación queda en estado `PENDING_REVIEW` (HITL obligatorio).
2. Se notifica al **Oficial de Cumplimiento** de forma urgente.
3. El Oficial tiene 24 horas para confirmar si es un falso positivo o una coincidencia real.
4. **Falso positivo**: Se documenta y la reclamación continúa su flujo normal con DDS.
5. **Coincidencia confirmada**: Se paraliza el pago y se reporta a las autoridades competentes.

---

## 4. Excepciones a la Debida Diligencia

No se requiere debida diligencia en los siguientes casos:

- **Instituciones estatales dominicanas o extranjeras** reconocidas oficialmente.
- **Pagos ordenados por decisión judicial firme** (sentencia ejecutoriada).

Estas excepciones deben documentarse explícitamente en el expediente.

---

## 5. Umbrales de Escala y Reportes

| Monto del pago | Acción requerida |
|----------------|-----------------|
| ≤ RD$100,000 | DDS estándar |
| RD$100,001 – RD$500,000 | DDS + revisión supervisor |
| > RD$500,000 | DDS/DDA + doble aprobación (Director + Abogado) |
| Cualquier monto si hay flag OFAC | DDA + Oficial de Cumplimiento |

---

## 6. Conservación de Documentos

Todos los expedientes de debida diligencia **deben conservarse durante 10 años**
desde la fecha del último pago de la reclamación, en cumplimiento de la normativa
dominicana contra el LA-FT.

Los expedientes se almacenan en:
- **Formato digital**: Sistema ArNes (escaneados y validados)
- **Formato físico**: Archivo central de Seguros Pepín (hasta digitalización completa)

---

## 7. Responsabilidades

| Rol | Responsabilidad |
|-----|----------------|
| Auxiliar de Reclamaciones | Ejecutar DDS en cada reclamación; registrar resultado |
| Analista de Reclamaciones | Supervisar DDS; resolver casos complejos de perfil |
| Oficial de Cumplimiento | Aprobar/rechazar DDA; reportar casos LA-FT; actualizar listas |
| Director de Reclamaciones | Autorizar pagos > RD$500,000; recibir alertas HIGH de judicialización |

---

## 8. Integración con Smart-Claims Agent

El **Agente G** automatiza el proceso de debida diligencia:

- **Paso 1**: Búsqueda automática en OFAC/ONU mediante fuzzy matching.
- **Paso 2**: Cálculo del score de fraude heurístico basado en PEPIN-POL-CP-0006:
  - Daños propios con monto > RD$500,000: +20 puntos
  - 3 o más reclamaciones previas: +25 puntos | 2 reclamaciones: +10 puntos
  - Incidente entre 00:00 y 04:59: +15 puntos
  - Documentación incompleta: +10 puntos
- **Resultado**: Score 0.0–1.0 → `simplificada` (score ≤ 0.50) o `ampliada` (score > 0.50 o OFAC flagged)

---

## 9. Marco Legal y Normativo

- Ley No. 155-17 contra el Lavado de Activos y Financiamiento del Terrorismo (RD)
- Ley No. 146-02 sobre Seguros y Fianzas de la República Dominicana
- Ley 172-13 sobre Protección de Datos de Carácter Personal
- Resolución SB No. 002-12 (Banco Central RD) — aplicación análoga al sector seguros
- Normativas OFAC (Office of Foreign Assets Control, US Treasury)
- Listas de sanciones ONU (Consejo de Seguridad)
- Política interna PEPIN-POL-CP-0006 (v.0005, 04/04/2023)
