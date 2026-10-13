# Línea base del proceso actual (SCRUM-95/96)

Mide en el historial de WhatsApp **cómo se atiende hoy**, para comparar con el
asistente en el piloto.

| Métrica | Hoy (export de WhatsApp) | Con el asistente (panel) |
|---|---|---|
| Tiempo de primera respuesta | este script | inmediato (el bot responde) |
| Tiempo hasta confirmar una cita | este script | "Tiempo hasta confirmar" |
| Variación entre precio dicho y final | este script (indicativo) | "Desviación cotizado vs cobrado" |

## Cómo correrlo

1. La propietaria exporta cada chat desde WhatsApp Business: **Más → Exportar
   chat → Sin archivos**. Idealmente los chats de clientes de los últimos 3–6 meses.
2. Guardar los `.txt` en `datos_crudos/chats/`. Esa carpeta está en `.gitignore`:
   **nunca se sube**.
3. Ejecutar:
   ```
   python -m evaluacion.linea_base.linea_base_whatsapp --exports datos_crudos/chats --propietaria "<nombre con el que aparece ella>"
   ```
4. Revisar a mano `datos_crudos/chats/revision_linea_base.json`: la detección es
   por reglas. Descartar falsos positivos y anotar cuántos hubo.
5. Solo `resultados/linea_base.json` (cifras agregadas, sin nombres ni textos) va al repo y al informe.

**¿Por qué no usar el corpus anonimizado?** El anonimizador de SCRUM-63 guarda la
fecha pero no la hora de cada mensaje; sin la hora no se pueden medir tiempos.

Al cierre del proyecto se elimina `datos_crudos/` (protocolo LOPDP de SCRUM-63).
