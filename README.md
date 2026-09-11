# Lina's Pet Salón - Asistente WhatsApp (Proyecto MIA)

Backend del sistema multiagente conversacional para automatizar atención,
cotización y agendamiento de citas de grooming, vía WhatsApp Business Cloud API.

## Estado actual

- [x] Estructura base del repo
- [x] Servidor FastAPI mínimo (`GET /`, `GET /webhook` para verificación de Meta)
- [ ] `POST /webhook` para recibir mensajes reales (SCRUM-83)
- [ ] Envío de mensajes salientes (SCRUM-84)
- [ ] Primer nodo de LangGraph (SCRUM-85)

## Cómo correrlo localmente

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# completa WHATSAPP_VERIFY_TOKEN con cualquier string que tú definas

uvicorn app.main:app --reload --port 8000
```

Prueba local de verificación (simula lo que hace Meta):

```bash
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=TU_TOKEN&hub.challenge=1234"
```

Debe devolver `1234`. Si devuelve 403, revisa que `WHATSAPP_VERIFY_TOKEN`
en tu `.env` coincida exactamente con lo que mandaste en el `curl`.

## Siguiente paso

1. Desplegar esto a Railway.
2. Crear la app en Meta for Developers, agregar el producto WhatsApp.
3. En la configuración del webhook de la app de Meta, pegar la URL de
   Railway (`https://tu-app.up.railway.app/webhook`) y el mismo
   `WHATSAPP_VERIFY_TOKEN` que pusiste en tu `.env`.
4. Meta hará el `GET /webhook` de verificación automáticamente al guardar.
