# Reunión con la propietaria: lo que necesitamos de ella

Una sola reunión de unos 60 minutos, idealmente con el celular y el computador
a mano. Llevar esta hoja impresa, anotar las respuestas al lado y después
pasárselas a Claude para actualizar el sistema.

**Antes de la reunión**, pedirle que tenga a mano:
- RUC del negocio;
- un documento con el nombre y la dirección del negocio (planilla de servicios o certificado del SRI);
- acceso a su Facebook personal (para crear o administrar el portfolio de Meta);
- su iPhone y, si tiene, su cuenta de Google (para el calendario del negocio, sección 2b).

---

## Respuestas de la reunión del 17-oct-2026 (ya aplicadas en el sistema)

| Tema | Lo que dijo | Cómo quedó |
|---|---|---|
| Turnos | Agenda cada 2 horas, desde las 8 hasta las 4 | Citas solo a las 08:00, 10:00, 12:00, 14:00 y 16:00 (`config_agenda.json`) |
| Foto | Que la foto le llegue primero a ella para decidir el tamaño | La foto se le reenvía con lo que estimó el sistema; ella responde citándola y le llega al cliente. Al cliente ya no se le da el rango por foto |
| Pedir foto | Pedirle al cliente una foto del perro | Se pide una vez, después del servicio y el nombre (no si la mascota ya vino antes) |
| Preguntas | Nombre, vacunas, desparasitado, nervioso o agresivo, servicio | Se agregó vacunas y desparasitación (sale en el resumen de la cita) y "agresivo" en la pregunta de comportamiento |
| Nudos | Recargo fijo de 2 o 3 $, no por porcentaje; quitar motas se cobra más y lo ve ella | Nudos: +2 a 3 $ fijos. Motas (muy enredado): rango orientativo, ella fija el valor al aprobar |
| Comportamiento | Nervioso o miedoso no paga más, salvo casos especiales | Sin recargo; agresivo se sigue rechazando |
| Deslanado | Es parte del Baño Completo (doble capa y pelo corto) | Ya no se ofrece aparte: si lo piden, se agenda un Completo |
| Gastos médicos | El dueño asume los gastos médicos causados por la mascota | Agregado a las políticas (base de conocimiento) |
| Memoria de clientes | Que recuerde a los clientes | Reconoce a la mascota por su nombre y reusa raza, tamaño y pelo de citas anteriores |
| Tamaños | Miniatura, pequeño, mediano, grande y extragrande | El cliente puede decirlos; **falta** que ella dé precios propios para miniatura y extragrande (hoy se cotizan como pequeño y grande) |
| Asistente virtual | Preguntó si sería mejor que no se sepa | Recomendación del equipo: decirlo (transparencia y LOPDP). Se acortó el aviso de bienvenida |

**Pendiente de aclarar con ella:**
- "Si piden un baño premium pero es solo baño medicado, es un baño completo y el precio no cambia": ¿el baño medicado se hace dentro del Completo al mismo precio?
- Precios de miniatura y extragrande, y sus rangos de peso.
- Qué días atiende (hoy el sistema ofrece todos los días).

---

## 1. Presentación (5 min)

- Mostrarle el panel (pestaña **Demo en vivo**). Hacer una conversación de
  ejemplo: un cliente cotiza y agenda, y ella aprueba con "listo".
- Explicarle la regla de oro: **ninguna cita se confirma sin su aprobación**,
  y puede apagar el bot cuando quiera ("pausar bot").
- Entregarle la [guía de una página](guia_propietaria.md).

## 2. WhatsApp: decisiones (15 min)

**2.1 ¿Qué número usará el asistente?**

| Opción | Ventaja | Desventaja |
|---|---|---|
| **Número nuevo** (chip aparte) | Ella conserva su WhatsApp Business como está | Hay que avisar a los clientes del piloto |
| **Su número actual** | Los clientes escriben al mismo número | Deja de funcionar en la app del celular: solo atiende por el bot y por "pausar bot" |

Recomendación para el piloto: **número nuevo**.

Respuesta: ______________________

**2.2 Cuenta del negocio en Meta**

Meta exige que la empresa esté **verificada a nombre del negocio**, con su RUC.
Por eso lo hace ella; no se puede desde la cuenta de un estudiante.

1. ¿Ya tiene un portfolio empresarial de Meta, por ejemplo porque maneja anuncios de Facebook o Instagram? Sí / No
2. Si no tiene, se crea en [business.facebook.com](https://business.facebook.com) con su Facebook.
3. **Verificación de la empresa:** nombre legal, dirección, teléfono y el documento con RUC. Meta tarda entre 1 y 14 días.
4. Que **nos agregue como administradores** del portfolio, para configurar la app y el webhook.

Datos: nombre legal ______________________ · RUC ______________ · correo del negocio ______________

**2.3 Nombre visible del asistente en WhatsApp** (lo aprueba Meta): ________________

## 2b. Calendario del negocio en su iPhone (10 min)

Ella usa el app **Calendario del iPhone**. El bot no puede escribir en el
calendario de iCloud (Apple no ofrece una API oficial), pero sí en uno de
Google, que **aparece dentro del mismo app Calendario**: no cambia de app.

**Con el iPhone de ella en la mano:**
1. Si no tiene cuenta de Google, crear una para el negocio (por ejemplo
   `linaspetsalon@gmail.com`).
2. En [calendar.google.com](https://calendar.google.com) (desde el computador):
   **Otros calendarios → + → Crear calendario**, con el nombre "Lina's Pet Salón".
3. En el iPhone: **Ajustes → Calendario → Cuentas → Añadir cuenta → Google**,
   iniciar sesión y dejar activado **Calendarios**.
4. En **Ajustes → Calendario → Calendario por omisión**, elegir **"Lina's Pet Salón"**.
   **Este paso es clave:** si queda iCloud por omisión, lo que ella anote nuevo
   no lo ve el bot, que podría ofrecer un horario ocupado.
5. Abrir el app Calendario → **Calendarios** (abajo) y verificar que aparece
   "Lina's Pet Salón" activado.
6. Nosotros, después de la reunión: compartir ese calendario con la cuenta de
   servicio del bot ("Hacer cambios en eventos") y poner su ID en Railway
   (`GOOGLE_CALENDAR_ID`). Pasos en `docs/plan_cierre.md`, A3.

**Qué cambia para ella:**
- Las citas que aprueba **aparecen solas** en su Calendario, con mascota, servicio y modalidad.
- Lo que anote en "Lina's Pet Salón" (citas por fuera del bot, días libres, bloqueos) el bot lo
  respeta y no ofrece esos horarios.
- Sus eventos personales pueden seguir en iCloud; el bot no los ve. Si quiere que un compromiso
  personal bloquee la agenda, lo anota en "Lina's Pet Salón".

Datos: correo de Google del calendario ______________________ · ¿Se configuró en el iPhone? Sí / No

## 3. Precios por validar (15 min)

Preguntar uno por uno con el ejemplo concreto. Marcar ✔ si está bien o
escribir el precio correcto. *(Hoy son supuestos del equipo).*

**Baño completo, sin nudos y perro tranquilo:**

| Tamaño y tipo de pelo | Ejemplo | Precio actual | ¿Correcto? |
|---|---|---|---|
| Pequeño, doble capa | pomerania(manto largo y deligado - $18), pug(pelo corto - $12) | 12 $ |  |
| Pequeño, pelo de cepillado | (mestizo pequeño de pelo largo) | 15 $ |tiene pelo largo, corto , suabe duro? | putbul puede ser $18
| Pequeño, pelo corto | chihuahua, salchicha | 12 $ | |
| Mediano, doble capa | (mestizo mediano con subpelo) | 15,50 $ | |
| Mediano, pelo de cepillado | border collie | 20 $ | |
| Mediano, pelo corto | beagle, bulldog francés | 12,50 $ | |
| Grande, doble capa | husky, labrador, pastor alemán | 24 $ | |

**Recargos y reglas:**

| Pregunta | Hoy el sistema hace | Respuesta |
|---|---|---|
| Perro **nervioso o difícil**: ¿cuánto más cobra? | "Entre 0 y 20 %" (ancho, por eso casi nunca da precio exacto) | |
| Nudos **moderados** en perro pequeño | +17 % | |
| Nudos **moderados** en perro grande | +28 % | |
| Nudos **severos** en perro mediano | +45 % | |
| Deslanado de perro **mediano** | 15–25 $ | |
| El deslanado, ¿se suma al baño o se cobra aparte? | Aparte | |
| Descuento por varias mascotas: "más de 3", ¿es desde 3 o desde 4? | Desde 4, 1–2 $ por mascota | |
| Con varios perros a domicilio, ¿el traslado se cobra una sola vez? | Una vez | |
| ¿Qué sectores son "aledaños" (traslado 0–3 $)? | Ninguno definido | |
| La Carolina: ¿10 $ o 15 $? | 10–15 $ | |
| IVA: ¿está en RIMPE? ¿Los precios ya incluyen IVA? | No suma IVA | |

**Razas que pusimos nosotros.** Confirmar el tipo de pelo y el tamaño de las que más le llegan:
poodle, maltés, bichón, lhasa apso, cocker, pomerania, labrador, pastor alemán,
samoyedo, border collie, beagle, bulldog francés, pitbull, rottweiler, yorkie,
pequinés, chihuahua y salchicha.

## 4. Cómo funciona el asistente (10 min)

| Pregunta | Propuesta actual | Respuesta |
|---|---|---|
| Horario: L, X y V de 11:00 a 18:00; M, J, S y D de 08:00 a 18:00 | (del historial de WhatsApp) | |
| Si no responde una solicitud: recordatorio a los 45 min, máximo 2, solo entre 07:00 y 21:00 | | |
| Si falta 1 h para la cita sin aprobar, se le ofrecen otros horarios al cliente | | |
| Pedidos especiales ("sin el accesorio"): ¿el bot menciona precio? | No, salvo que el cliente pregunte; entonces dice que ella lo valida |el bot puede dar costos estimados pero se tiene que validar con la dueña |
| ¿Cuánto dura cada servicio? (para no cruzar citas) | Supuestos: completo pequeño 1:30–2 h; grande 2:30–4 h | de 1:30 a 2 pero depende del perro, si es grande de 3 a 4h como el husky|
| ¿Cuántas mascotas atiende a la vez? | Una |si, amenos que sean de la misma casa y se les da descuento, solo bajo aprobacion |
| Correo para el respaldo cuando falle WhatsApp | | |

**Aviso de privacidad** (lo recibe cada cliente la primera vez). Leérselo y confirmar:

> "Hola 👋 Le atiende el asistente virtual de Lina's Pet Salón: respondo de
> forma automática y la propietaria revisa cada cita antes de confirmarla. Los
> datos que me comparta (nombre, número, datos y fotos de su mascota, sector si
> pide puerta a puerta) se usan solo para cotizar y agendar, conforme a la Ley
> Orgánica de Protección de Datos Personales. Si desea consultar, corregir o
> eliminar sus datos, escríbalo aquí y la propietaria le atiende."

✔ / cambios: ______________________

## 5. Información que el asistente hoy no sabe (5 min)

| Pregunta de clientes | Respuesta |
|---|---|
| Dirección exacta del salón |dar la ubicacion, tratar de que los clientes vengas antes de ofrecer puerta a puerta al centro norte de quito $8, si es cerca no tiene costo. llano chico $5  |
| ¿Acepta efectivo o tarjeta, además de transferencia? |no tarjeta |
| ¿El cliente puede quedarse durante el servicio? |si lo solicita. o si van a ayudar |
| ¿Atiende gatos? |no |
| Hospedaje y snacks: ¿el bot da algún dato o siempre se lo pasa a ella? | no se menciona |

Y repasar con ella el contenido de la base de conocimiento: checklist de la
sección 5 de `app/rag/ESQUEMA_CONTENIDO.md`.

## 6. Datos para medir el proyecto (5 min)

Para comparar "antes y después" del asistente:
1. **Tiempo hasta confirmar una cita hoy:** ¿cuánto tarda normalmente? (el proyecto declara de 30 min a 2 h)
2. **Diferencia entre lo cotizado y lo cobrado hoy:** ¿cada cuánto cobra distinto de lo que dijo, y por cuánto?
3. **Historial:** ¿nos autoriza a usar el export de WhatsApp *anonimizado* (sin nombres ni números) para medirlo?
   Si dice que sí, entregarle la hoja [exportar_whatsapp.md](exportar_whatsapp.md) y, si hay tiempo, hacer con ella el primer chat en la misma reunión.
   El chat con una clienta frecuente ya lo tiene Ocampo (SCRUM-72): pedir **chats de otros clientes** para
   que la línea base sea representativa.
4. **Registro de Excel:** ya lo tiene Ocampo (28 hojas, sept-2024 a sept-2026), **no hay que pedírselo**.
   Solo preguntarle lo que Ocampo no haya sabido responder:

   | Pregunta | Respuesta |
   |---|---|
   | SC = |servicio completo |
   | SB = |solo baño|
   | SP = |servicio primio |
   | BA = |pulgas |
   | BM = | medicado|
   | BB = |blanqueadr |
   | SBas = | servicio basico|
   | El precio anotado, ¿es antes o después del descuento? | |
   | ¿Incluye el traslado puerta a puerta? | |
   | Con varias mascotas, ¿una fila por mascota o por visita? | |
5. Durante el piloto, ¿se compromete a escribir **"cobré X a la cita #N"** después de cada atención?
6. **Clientes para el piloto:** ¿a quiénes invitamos? (unos 10–12 de confianza)

## 6b. Clasificar 48 fotos a ciegas (1 min en la reunión; ella lo hace después)

Es la referencia independiente para evaluar el clasificador de fotos (SCRUM-105).
Las etiquetas del equipo partieron de propuestas de Gemini; las de ella no.

**Antes de la reunión (Nico, 5 min):**
1. `python -m entrenamiento.clasificador_imagen.formulario_ciego script` genera `READ/formulario_ciego.gs`.
2. En [script.google.com](https://script.google.com): **Nuevo proyecto**, pegar todo el archivo, **Guardar**,
   elegir `crearFormulario` y **Ejecutar** (autorizar Drive y Forms la primera vez).
3. En **Registro de ejecución** aparece el **ENLACE PARA LA PROPIETARIA**. Abrirlo una vez y revisar que se ven las fotos.

**En la reunión:** explicarle en un minuto qué es y mandarle el enlace por WhatsApp.
- Lo responde desde el celular cuando pueda (unos 15 min): tamaño, tipo de pelo y estado de cada foto, como lo haría al cotizar.
- **No le sugerimos nada.** Si pregunta, solo se le explican las opciones.
- Pedirle una fecha, por ejemplo dentro de 2–3 días.

**Cuando responda:**
- En el formulario: **Respuestas → Ver en Hojas de cálculo → Archivo → Descargar → CSV**.
- Después:
  ```
  python -m entrenamiento.clasificador_imagen.formulario_ciego importar --respuestas <csv descargado>
  python -m evaluacion.imagen.comparar_cnn_gemini --predicciones-cnn READ/modelo/clasificador_v1_predicciones_test.csv --imagenes READ/para_colab/dataset --solo-lectura --estandar-oro READ/estandar_oro_propietaria.csv
  ```

**Respaldo:** si prefiere hacerlo en la reunión, `python -m entrenamiento.clasificador_imagen.revisar --ciego`
y compartir pantalla. Ella dice la respuesta y Nico hace clic.

## 7. Consentimiento (2 min)

- Autoriza el uso del sistema en un piloto académico (UDLA) y de los datos
  anonimizados para el informe.
- Autoriza usar las fotos de su álbum de Facebook, ya anonimizadas, para entrenar el clasificador de imagen.

Firma o confirmación por escrito: ______________________

---

## Después de la reunión

| Quién | Qué |
|---|---|
| Claude | Actualizar tarifario, horario, contenido, aviso y tiempos con las respuestas, y re-indexar |
| Nico | Con el portfolio verificado: app de Meta del piloto, número, plantillas y webhook ([despliegue.md](despliegue.md), fase 3) |
| Nico | Calendario del negocio compartido con la cuenta de servicio, y su correo en `CORREO_PROPIETARIA` |
| Equipo | Capacitación con la [guía](guia_propietaria.md) y fecha de inicio del piloto |
