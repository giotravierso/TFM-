# Ficha de Proceso — SP-PCS-022: Reclamación Judicializada
## Seguros Pepín, S.A. — Versión académica PoC Smart-Claims Agent

---

## 1. Objetivo

Gestionar las reclamaciones de seguros de vehículos que no se resuelven de forma
amistosa y derivan en proceso judicial, garantizando la defensa legal de Seguros
Pepín y minimizando el costo total del litigio.

Estadísticamente, aproximadamente el **10% de las reclamaciones** de Seguros Pepín
terminan judicializadas. El sistema Smart-Claims implementa el **subproceso de
prevención SP-PCS-022.3** mediante el Agente F, que predice esta probabilidad.

---

## 2. Factores de Riesgo de Judicialización

Los siguientes factores aumentan la probabilidad de que una reclamación derive en litigio:

| Factor | Impacto |
|--------|---------|
| Monto reclamado > RD$300,000 | Alto |
| Propuesta rechazada anteriormente por el reclamante | Muy alto |
| Múltiples reclamaciones previas del mismo cliente (≥2) | Medio |
| Alto número de interacciones sin resolución (>5) | Medio |
| Tipo RC o DPA (responsabilidad con terceros) | Alto |
| Tiempo de atención superior a 30 días desde apertura | Medio |
| Canal telefónico (sin registro escrito) | Bajo-Medio |

---

## 3. Proceso de Gestión de Reclamación Judicializada

### 3.1 Pasos del Proceso SP-PCS-022

1. **Recepción de notificación judicial**: El área legal recibe la demanda del juzgado.
2. **Asignación de abogado**: El Director de Reclamaciones asigna abogado interno o externo.
   - Abogado interno: casos con monto estimado ≤ RD$1,000,000.
   - Abogado externo: casos complejos o que superen ese límite.
3. **Revisión del expediente**: El abogado revisa toda la documentación del caso.
4. **Estrategia de defensa**: Se define si se negocia acuerdo o se litiga.
5. **Seguimiento de audiencias**: El abogado registra fechas y actualizaciones.
6. **Propuesta de acuerdo**: Si procede, se hace oferta al demandante.
7. **Resolución**: Acuerdo extrajudicial o sentencia judicial.
8. **Cierre y pago**: Tesorería ejecuta el pago según el acuerdo o sentencia.

### 3.2 Reglas del Proceso Judicializado

| Código | Regla |
|--------|-------|
| R-SP-PCS-22-001 | El abogado interno solo puede proponer acuerdos hasta RD$1,000,000 sin aprobación adicional. Por encima de ese monto, requiere aprobación del Director de Reclamaciones y del Comité. |
| R-SP-PCS-22-002 | Los honorarios de abogados externos se facturan cada 30 días. Las facturas deben registrarse en el sistema dentro de los 5 días hábiles de recibidas. |
| R-SP-PCS-22-003 | Los cheques no retirados en un plazo de 3 meses desde su emisión serán cancelados automáticamente. Se notificará al reclamante o su representante legal antes de la cancelación. |
| R-SP-PCS-22-004 | El sistema debe notificar al abogado 5 días antes de cada audiencia programada (pain point H258 del AS-IS). |
| R-SP-PCS-22-005 | El apoderamiento del abogado debe registrarse en el sistema inmediatamente (pain point H256 del AS-IS). |

---

## 4. Subproceso de Prevención SP-PCS-022.3 (TO BE — Smart-Claims)

El **Agente F** del sistema Smart-Claims implementa este subproceso, que **no existe**
en la empresa real como proceso automatizado (identificado como oportunidad en el
análisis AI Readiness).

### 4.1 Funcionamiento del Agente F

El Agente F utiliza un modelo **XGBoost** entrenado con datos históricos sintéticos
para predecir la probabilidad de judicialización de cada reclamación en tiempo real.

**Features utilizados (10):**
1. `amount_requested / 1,000,000` — monto normalizado
2. `prior_claims_count` — reclamaciones previas del cliente
3. `days_since_incident` — días desde el incidente
4. `interaction_count` — número de interacciones sin resolución
5. `proposal_rejected_before` — si el reclamante rechazó propuesta previa (0/1)
6. `claim_type_RC` — tipo Responsabilidad Civil (0/1)
7. `claim_type_DPA` — tipo Daños a Propiedad Ajena (0/1)
8. `claim_type_danys_propis` — tipo Daños Propios (0/1)
9. `risk_score` — score de fraude/riesgo del Agente G
10. `channel_phone` — canal telefónico (0/1)

**Niveles de riesgo:**
- **HIGH** (probabilidad > 60%): Alerta inmediata al Director de Reclamaciones
- **MEDIUM** (probabilidad 30–60%): Seguimiento preventivo activo
- **LOW** (probabilidad < 30%): Gestión estándar

### 4.2 Acciones según nivel de riesgo

| Nivel | Acción del sistema |
|-------|--------------------|
| HIGH | Notificación urgente al Director de Reclamaciones para intervención proactiva |
| MEDIUM | Flag en el expediente; revisión por Analista de Reclamaciones en 48h |
| LOW | Procesamiento estándar |

---

## 5. Pain Points AS-IS que resuelve este proceso (TO BE)

| ID | Problema actual | Solución Smart-Claims |
|----|-----------------|----------------------|
| H156 | ~10% de reclamaciones judicializadas sin predicción ni prevención | Agente F predice riesgo en tiempo real |
| H256 | Sistema no notifica trazabilidad del apoderamiento del abogado | Registro automático al asignar abogado |
| H257 | Abogado solo sabe estatus cuando llega notificación del juzgado | Notificaciones automáticas por audiencia |
| H258 | Sin recordatorio automático al abogado de fechas de audiencia | Alertas 5 días antes de cada audiencia |
| H262 | Duplicidad en envío de correo para apoderar abogados | Proceso unificado en el sistema |
| H263 | Cheque cancelado sin comunicar al reclamante | Notificación automática antes de cancelación |
| H278 | Facturas de abogados por correo sin integración | Integración de honorarios en el sistema |

---

## 6. Marco Legal

- Código de Procedimiento Civil de la República Dominicana
- Ley No. 146-02 sobre Seguros y Fianzas
- Procedimiento Interno PEPIN-PRD-LR-0001 (v.0001, 16/12/2022)
- Reglamento de la Superintendencia de Seguros y Reaseguros
