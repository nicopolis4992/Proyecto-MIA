# Plan de cierre: pasos para las pruebas reales y el fin del proyecto

Versión 11-oct-2026. Cada paso dice **quién** lo hace, **qué se necesita** y
**cómo se sabe que está listo**. Los pasos marcados **(Claude)** se hacen en
una sesión de código: solo hace falta pedirlos.

Orden recomendado: **A → B en paralelo con C → D → E.**

---

## A. Pruebas reales con el equipo

### A1. Desplegar en Railway sin WhatsApp (15 min) — Nico

1. [railway.com](https://railway.com) → **New Project → Deploy from GitHub repo** → `Proyecto-MIA`.
2. Servicio → **Settings → Source → Branch**: `prototipo-s4`.
3. **Settings → Networking → Generate Domain**.
4. Clic derecho en el servicio → **Attach volume** → *mount path* `/data`.
5. **Variables → Raw Editor**:
   ```
   MIA_MODO=pruebas
   GEMINI_API_KEY=<tu clave>
   MIA_DB_PATH=/data/mia.sqlite3
   DEMO_CLAVE=<inventa una clave larga>
   ```
6. Esperar a que el despliegue quede en verde (**Deployments**).

**Listo cuando:**
- `https://<dominio>/` responde `{"modo": "pruebas", ...}`;
- `https://<dominio>/panel?clave=<DEMO_CLAVE>` abre el panel;
- en "Demo en vivo", "hola" recibe respuesta.

**Si falla:** **Deploy Logs**. Lo más común es una variable mal escrita.

### A2. Conectar WhatsApp (20 min) — Nico, cuando tengas el token

1. Meta → tu app → **WhatsApp → Configuración de la API**:
   - copiar el **Phone number ID**;
   - en "Para", **agregar los números del equipo** (máximo 5). Cada uno confirma con el código que le llega.
2. En Railway, agregar:
   ```
   WHATSAPP_ACCESS_TOKEN=<token permanente>
   WHATSAPP_PHONE_NUMBER_ID=<id>
   WHATSAPP_VERIFY_TOKEN=<cadena inventada>
   NUMEROS_PERMITIDOS=593...,593...
   PROPIETARIA_WHATSAPP=593...   (un compañero hace de propietaria)
   ```
3. Meta → **WhatsApp → Configuración → Webhook → Editar**:
   - URL: `https://<dominio>/webhook`;
   - token: el mismo `WHATSAPP_VERIFY_TOKEN`;
   - **Verificar y guardar**;
   - en "Campos del webhook", **suscribir `messages`**.

**Listo cuando:** escribes "hola" al número de prueba desde tu celular y
recibes el aviso de privacidad y la respuesta.

**Si no llega nada:**
- revisar que `messages` esté suscrito;
- revisar que tu número esté en `NUMEROS_PERMITIDOS`;
- revisar Deploy Logs.

El token temporal de la consola **vence en 24 h**. Para no tener que renovarlo:
Business Settings → **Usuarios del sistema** → Agregar (Admin) → **Asignar
activos** (la app y la cuenta de WhatsApp) → **Generar token**, sin
vencimiento, con `whatsapp_business_messaging` y `whatsapp_business_management`.

### A3. Google Calendar de pruebas (20 min) — Nico

1. [console.cloud.google.com](https://console.cloud.google.com):
   - crear el proyecto "MIA";
   - **APIs y servicios → Biblioteca → Google Calendar API → Habilitar**.
2. **APIs y servicios → Credenciales → Crear credenciales → Cuenta de servicio**
   (nombre "mia-bot"), sin roles. En la cuenta: **Claves → Agregar clave → JSON**.
   Se descarga un archivo: **no subirlo al repo**.
3. [calendar.google.com](https://calendar.google.com) → **Otros calendarios → Crear**
   "Lina's Pet Salón (pruebas)". En su configuración:
   - **Compartir con personas**: agregar el correo de la cuenta de servicio
     (`mia-bot@...iam.gserviceaccount.com`) con **"Hacer cambios en eventos"**;
   - copiar el **ID del calendario** (sección "Integrar el calendario").
4. En Railway:
   - `GOOGLE_CALENDAR_ID=<id>`;
   - `GOOGLE_SERVICE_ACCOUNT_JSON=<pegar el contenido completo del JSON>`.

**Listo cuando:** aprobaste una cita en la demo y aparece en el calendario.

### A4. Correo de respaldo (10 min) — Nico

1. Crear una cuenta de Gmail para el bot (p. ej. `linaspet.asistente@gmail.com`).
   Mejor no usar la personal.
2. En esa cuenta:
   - activar la **verificación en dos pasos**;
   - abrir [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
     y crear una contraseña de aplicación "MIA". Son 16 letras; copiarlas sin espacios.
3. En Railway:
   ```
   CORREO_USUARIO=linaspet.asistente@gmail.com
   CORREO_CLAVE=<16 letras>
   CORREO_PROPIETARIA=<tu correo, en pruebas>
   ```

**Listo cuando:** "Estado del sistema" muestra "Correo de respaldo: configurado".
Para probarlo de verdad: poner un `WHATSAPP_ACCESS_TOKEN` inválido un momento,
crear una cita en WhatsApp y ver que el resumen llega por correo. Después,
restaurar el token.

### A5. Plantillas de Meta (10 min + 1–2 días de espera) — Nico

1. Meta Business Suite → **Administrador de WhatsApp → Plantillas de mensajes → Crear plantilla**.
2. Crear las dos de [plantillas_meta.md](plantillas_meta.md):
   - categoría **Utilidad**;
   - idioma **Español**;
   - el cuerpo exacto;
   - el ejemplo de `{{1}}`.
3. Cuando estén **Aprobadas**, en Railway:
   ```
   WHATSAPP_PLANTILLA_PROPIETARIA=aviso_propietaria
   WHATSAPP_PLANTILLA_CLIENTE=aviso_cliente
   ```

Hasta entonces, quien hace de propietaria debe escribirle al bot cada mañana
para que se abra la ventana de 24 h.

### A6. Guion de pruebas (1 h) — (Claude)

Casos repartidos por persona: quién es cliente, quién propietaria, qué escribir
y qué debe pasar, con una hoja para anotar cada falla. Sale del catálogo de
SCRUM-88; si aún no está, se usan los escenarios grabados y los casos del
registro de errores.

### A7. Sesión de pruebas (1–2 días) — Equipo

- Cada uno sigue su parte del guion y además conversa libremente, como lo haría un cliente.
- Anotar en la hoja: hora, número, qué escribió, qué esperaba y qué pasó.
- Al final del día, revisar el panel: citas, no entregados y desviación de cobro.

### A8. Correcciones — (Claude) + Nico

Se pasa la hoja a Claude:
- se corrige cada falla con su prueba automática;
- se agrega al [registro de errores](../evaluacion/registro_errores.md);
- se redespliega.

Railway redespliega solo con cada `git push`.

---

## B. Modelo de imagen (CNN)

### B9. Terminar la revisión de etiquetas (~1–2 h) — Nico

```
python -m entrenamiento.clasificador_imagen.revisar --etiquetas READ/etiquetas_propuestas.csv
```
- Se abre `http://localhost:8790`. Las fotos dudosas aparecen primero.
- Corregir tamaño, grupo y estado y marcar **R** (revisada y avanzar).
- Quedan 239 de 317.
- **Criterio:** etiquetar lo que haría la propietaria con esa foto. Si es
  imposible saberlo, poner `es_perro=no` o dejar una nota: esa foto no entra al entrenamiento.

**Listo cuando:** las 317 tienen `revisado = si`.

### B10. Manifiesto y entrenamiento en Colab (~1 h) — Nico

1. Construir el manifiesto (local, gratis):
   ```
   python -m entrenamiento.clasificador_imagen.preetiquetar manifiesto --etiquetas READ/etiquetas_propuestas.csv --salida READ/manifiesto_v2.csv
   ```
   Imprime cuántas imágenes y mascotas hay en train, val y test.
2. En Google Drive, crear `MIA/dataset/` y subir:
   - `manifiesto_v2.csv`;
   - una carpeta `imagenes/` con **todas** las fotos de `parte1/.../imagenes` y `parte2/.../imagenes` juntas.
3. Abrir `entrenamiento/clasificador_imagen/entrenar_colab.ipynb` en Colab
   (**Archivo → Subir cuaderno**) → **Entorno de ejecución → Cambiar tipo → GPU T4**.
4. Ejecutar las celdas, con estas rutas:
   - `--manifiesto /content/drive/MyDrive/MIA/dataset/manifiesto_v2.csv`;
   - `--salida /content/drive/MyDrive/MIA/modelos`.

   El repo se clona en el cuaderno. Si es privado, usar
   `https://<token>@github.com/...` o subir el zip del repo.
5. Descargar `clasificador_v1.onnx` y `clasificador_v1.json` y copiarlos a `app/vision/modelos/`.

**Listo cuando:** existen los dos archivos y el JSON tiene el F1 de validación y de prueba.

### B11. F1 por clase y Grad-CAM en el cuaderno — (Claude)

Se agrega al cuaderno antes de B10, para que el entrenamiento ya salga con
todas las métricas que pide SCRUM-105.

### B12. Evaluación de la CNN contra Gemini (SCRUM-105) — Loza

- Con el JSON y las imágenes de Grad-CAM: tabla por clase y comparación con
  Gemini en el mismo conjunto de prueba. El script de Gemini sobre ese conjunto lo deja Claude.
- Revisar en Grad-CAM que el modelo mire al perro y no la pañoleta o el marco.

### B13. Activar la CNN en el bot — (Claude)

- `onnxruntime` en `requirements.txt`.
- Recalibrar umbrales en `politica_imagen.json`.
- Pruebas y despliegue. `VISION_BACKEND=auto` la usa sola si el archivo existe.

---

## C. Evaluación para el informe

### C14. Preguntas para evaluar el RAG (SCRUM-71) — Loza

Un CSV con columnas `pregunta, respuesta_esperada, debe_declinar, categoria`:
- **~40 preguntas que la base sabe.** Ej: "¿cuánto cuesta el baño completo para
  un perro mediano?" → "<el valor del tarifario>" → `no` → `tarifario`.
- **~20 que no sabe** (sección 4 de `ESQUEMA_CONTENIDO.md`). Ej: "¿aceptan
  tarjeta?" → (vacío) → `si` → `politicas`.

Escribir las preguntas como las escribiría un cliente, con errores y sin tildes,
**sin mirar los documentos al redactarlas**.

### C15. Script de evaluación del RAG — (Claude)

- Calcula exactitud, "no sé" correctos, alucinaciones y recuperación top-k.
- Graba las respuestas de Gemini: repetir la evaluación es gratis.
- Propone el umbral de similitud con la curva de resultados.

### C16. Casos de uso (SCRUM-88) y ejecución (SCRUM-89) — Loza + (Claude)

1. Loza: catálogo con id, precondición, pasos, resultado esperado y prioridad.
   La cobertura mínima está en el comentario de SCRUM-88.
2. Claude: cada caso como escenario grabado (`scripts/escenarios.py`).
3. Ejecutar todos los escenarios y reportar el % de éxito. La meta es ≥ 85%.

### C17. Consolidar métricas (SCRUM-90) — Loza

Una tabla para el informe con:
- NLU: 0.958 (ya está);
- RAG (C15);
- CNN contra Gemini (B12);
- tiempo hasta confirmar y desviación de cobro, del panel durante las pruebas y el piloto.

### C18. Línea base del proceso actual (SCRUM-95/96) — (Claude) revisa, Loza reporta

Se revisa si el export de WhatsApp (el del NLU) permite medir sin la propietaria:
- **tiempo de respuesta:** del mensaje del cliente a la confirmación;
- **desviación de precio:** precio dicho frente a precio final.

Lo que no se pueda medir, se le pregunta a la propietaria en D.

---

## D. Con la propietaria

### D19–D20. Validaciones (1 reunión de ~45 min)

Llevar impreso:
1. El checklist de `app/rag/ESQUEMA_CONTENIDO.md`, sección 5 (contenido).
2. Precios: `app/cotizacion/LEEME_tarifario_v2.md`.
3. Horario de atención.
4. El texto del aviso de privacidad.
5. Tiempos de recordatorio: 45 min, máximo 2, vence 1 h antes.
6. Mencionar o no el precio de los pedidos especiales.

Corregir lo que diga. Claude actualiza los archivos y re-indexa.

### D21. Decidir el número de WhatsApp

| Opción | Ventaja | Desventaja |
|---|---|---|
| **Número nuevo** para el bot | Ella conserva su WhatsApp Business intacto | Los clientes deben guardar otro número |
| **Migrar su número** a la API | Los clientes escriben al mismo número | Deja de funcionar en la app del celular; solo atiende vía bot/pausa |

Recomendación para el piloto: **número nuevo**. Se anuncia a un grupo de clientes.

### D22. Calendario, correo y número de ella

Ella comparte su calendario del negocio con la cuenta de servicio (como en A3)
y da el correo donde quiere el respaldo.

### D23. Capacitación (20 min)

Con la [guía de una página](guia_propietaria.md) y practicando en el panel:
- aprobar, cambiar la hora, "cobré X a la cita #N", "pausar bot".

---

## E. Piloto y cierre

### E24. Pasar a `main` — Nico

```
gh pr create --base main --head prototipo-s4 --title "Prototipo S4" --body "Ver docs/plan_cierre.md"
```
Revisar, mezclar en GitHub y no volver a editar `main` directamente.

### E25. Entorno piloto — Nico (fase 3 de [despliegue.md](despliegue.md))

- **Environments → New** "piloto", con rama `main`.
- **Volumen nuevo**.
- Variables de `deploy/piloto.env.example`.
- App de Meta del negocio y sus plantillas.
- Webhook propio.

**Listo cuando:** "Estado del sistema" del piloto aparece todo en verde y
pasa una prueba de punta a punta con un número del equipo.

### E26. Piloto (1–2 semanas, S7-S8) — Equipo

- **Cada día:** un integrante revisa el panel del piloto (no entregados, pendientes, errores en los logs).
- **Al cerrar cada atención:** la propietaria escribe "cobré X a la cita #N".
- **Si algo falla:** "pausar bot" y avisar. La falla se corrige en pruebas y se pasa a `main`.

### E27. Resultados — Loza + equipo

- Exportar los indicadores del panel.
- Comparar contra la línea base (C18) y contra los objetivos: −50% de variabilidad, tiempo de agendamiento.

### E28. Recomendaciones (SCRUM-79/80/82 → 81) — Ocampo, luego (Claude)

- Ocampo entrega el catálogo JSON (formato en el comentario de SCRUM-79).
- Claude lo integra en la conversación.
- Si no alcanza el tiempo, se declara como trabajo futuro.

### E29. Supabase (SCRUM-74) — decisión del equipo

| Opción | Esfuerzo |
|---|---|
| Integrar (`RepositorioSupabase`) | ~4–6 h |
| Justificar SQLite con volumen para el volumen del piloto, con Supabase como trabajo futuro | 0 h |

Recomendación: justificar SQLite.

### E30. Revisiones pendientes en Jira

| Persona | Historias "En revisión" |
|---|---|
| Ocampo | 66, 99, 75, 76, 86 |
| Loza | 91, 95 |

Al aprobarlas, pasarlas a Finalizado.

### E31. Informe y presentación — Equipo

| Parte del informe | Fuente |
|---|---|
| Arquitectura | `memory-bank/` y el diagrama del orquestador |
| Métricas | C17 y E27 |
| Errores y limitaciones | `evaluacion/registro_errores.md` |
| Demo | el panel |
