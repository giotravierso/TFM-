# Ficha de Proceso — SP-PCS-009: Reclamación de Vehículos de Motor
## Seguros Pepín, S.A. — PEPIN-PRD-LR-0001 · v.0001 · 16/12/2022
## Versión académica PoC Smart-Claims Agent

---

## 1. Descripción del Proceso

El proceso SP-PCS-009 gestiona las reclamaciones de seguros de vehículos de motor
desde la notificación del siniestro hasta el pago al reclamante. Es el proceso de
mayor volumen en Seguros Pepín, con aproximadamente **10,000 expedientes anuales**.

### Tipos de reclamación cubiertos

| Código | Tipo | Cobertura | Límite | Deducible |
|--------|------|-----------|--------|-----------|
| danys_propis | Daños Propios | SÍ | RD$500,000 | RD$5,000 o 2% valor asegurado |
| DPA | Daños a Propiedad Ajena | SÍ | RD$1,000,000 | RD$0 |
| RC | Responsabilidad Civil | SÍ | RD$2,000,000 | RD$0 |
| robatori | Robo Total o Parcial | SÍ | RD$800,000 | RD$10,000 |
| danys_mecanics | Daños Mecánicos | NO | — | — |

---

## 2. Flujo Completo del Proceso (10 etapas)

### Etapa 1 — Aviso del Siniestro

El asegurado debe notificar a Seguros Pepín **dentro de las 24 horas** siguientes
al accidente (Art. 97, Ley 146-02). Canales aceptados: presencial, teléfono, email.

**Pain point AS-IS (H77):** Sin canal digital para apertura. El 100% de notificaciones
son presenciales o por teléfono. El sistema Smart-Claims habilita el canal digital.

### Etapa 2 — Recepción y Validación Documental

El **Auxiliar de Reclamaciones** verifica la documentación según el tipo:

**Daños Propios (danys_propis):**
1. Formulario Aviso de Accidente (PEPIN-FRM-LR-0003)
2. Acta Policial de DIGESETT (original o certificada)
3. Licencia de Conducir vigente (fotocopia)
4. Cédula de Identidad y Electoral (fotocopia)
5. Fotografías del vehículo dañado (mínimo 4, con placa visible)
6. Cotización de taller autorizado

**Daños a Propiedad Ajena (DPA):**
1. Aviso de Siniestro
2. Acta Policial de DIGESETT certificada con declaraciones de todas las partes
3. Acta de Conciliación (original)
4. Presupuesto de piezas y mano de obra (original, del taller del reclamante)
5. Fotografías del vehículo dañado con placa visible
6. Matrícula del vehículo a nombre del reclamante
7. Cédula de Identidad y Electoral del reclamante
8. Licencia de Conducir del reclamante
9. Carta de Cobertura (si el vehículo está asegurado en otra compañía)

**Responsabilidad Civil (RC):**
1. Aviso de Siniestro
2. Acta Policial de DIGESETT
3. Cédula de Identidad del reclamante
4. Licencia de Conducir del conductor involucrado
5. Fotografías del lugar del accidente y daños

**Robo Total o Parcial (robatori):**
1. Denuncia Policial (original, con sello y firma)
2. Licencia de Conducir del asegurado
3. Cédula de Identidad y Electoral
4. Matrícula del vehículo

**El Agente B** automatiza esta verificación en el sistema Smart-Claims.

### Etapa 3 — Apertura de Expediente

Se registra en el sistema ArNes y se asigna número de reclamación único.

**Pain point AS-IS (H86):** ~10,000 expedientes físicos anuales movilizados entre áreas.
**Pain point AS-IS (H149):** Carga manual de documentos escaneados en ArNes.

### Etapa 4 — Inspección Técnica

El **Inspector de Seguros** evalúa los daños, toma fotografías y determina si el
taller debe ser de la red autorizada.

**El Agente C** (Claude Vision) extrae datos estructurados de fotos y cotizaciones.

### Etapa 5 — Verificación de Cobertura

Se verifica que el tipo de siniestro está cubierto y se calculan los montos.

Reglas críticas:
- **R-SP-PCS-09-003**: Si el asegurado ya realizó otra reclamación en el mismo período,
  la cobertura disponible es solo el saldo restante (no el límite original).
- **R-SP-PCS-09-004**: El deducible siempre aplica. Si el monto tasado < deducible,
  el asegurado paga el total sin intervención de la aseguradora.

**El Agente D** realiza esta verificación mediante RAG sobre la póliza.

### Etapa 6 — Cotización y Licitación

El taller envía cotización. El inspector licita piezas en Infopiezas.net.

### Etapa 7 — Aprobación Doble

1ª aprobación: Director de Reclamaciones.
2ª aprobación: Abogado (en sistema PepínDesk).

Para montos > RD$500,000: revisión adicional del Comité (HITL automático en Smart-Claims).

**El Agente E** decide approve / reject / request_info con Chain-of-Thought.

### Etapa 8 — Reparación

El taller ejecuta la reparación con piezas y orden de compra aprobadas.

### Etapa 9 — Inspección Final

El inspector verifica la reparación completada antes de proceder al pago.

### Etapa 10 — Pago

Cheque emitido por Tesorería o transferencia bancaria (PEPIN-FRM-LR-0008).

**Regla R-SP-PCS-09-002**: Si el conductor no es el propietario de la póliza, el cheque
se emite siempre a nombre del propietario, no del conductor.

---

## 3. Umbrales HITL (Human-in-the-Loop) — SP-PCS-009 §3.3

| Condición | Acción |
|-----------|--------|
| Monto neto pagable ≤ RD$500,000 AND confianza ≥ 75% AND score fraude ≤ 30% | Aprobación automática |
| Monto neto pagable > RD$500,000 | Revisión del Director de Reclamaciones |
| Confianza en cobertura < 75% | Revisión por Analista de Reclamaciones |
| Score de fraude > 30% | Revisión por Área de Cumplimiento |
| Coincidencia en listas OFAC/ONU | Revisión urgente por Oficial de Cumplimiento |
| Total semanal de reclamaciones > RD$12,000,000 | Aprobación de Director Financiero |

---

## 4. Pain Points AS-IS Resueltos por Smart-Claims

| ID | Descripción | Agente |
|----|-------------|--------|
| H77 | Sin canal digital para apertura (100% presencial) | API + Streamlit |
| H78 | Cliente debe llamar/visitar para conocer estatus | Dashboard + notificaciones |
| H86 | 10,000 expedientes físicos anuales entre áreas | Expediente digital |
| H133 | Documentos de fianzas por WhatsApp | Canal oficial API |
| H149 | Carga manual de documentos escaneados en ArNes | Agente C (VLM) |
| H05 | Sistema no notifica fecha de entrega del vehículo | Notificaciones automáticas |
| H63 | Sin política de asignación automática de abogados | Agente F (predicción) |

---

## 5. KPIs del Proceso

| Indicador | AS-IS | Objetivo TO BE |
|-----------|-------|----------------|
| Días promedio de resolución | ~18 días | ≤ 10 días |
| Tasa de automatización | ~0% | ≥ 80% |
| Tasa de judicialización | ~10% | < 7% (prevención Agente F) |
| Reclamaciones fraudulentas detectadas | Manual | Automático (Agente G) |

---

## 6. Marco Legal

- Ley No. 146-02 sobre Seguros y Fianzas (Art. 97: aviso 24h)
- Ley 172-13 sobre Protección de Datos de Carácter Personal
- Reglamento de la Superintendencia de Seguros y Reaseguros
- Procedimiento Interno PEPIN-PRD-LR-0001 (v.0001, 16/12/2022)
- Política de Debida Diligencia PEPIN-POL-CP-0006 (v.0005, 04/04/2023)
