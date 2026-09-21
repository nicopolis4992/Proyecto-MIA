# Project Brief - Proyecto MIA / Lina's Pet Salón

## Que es
Capstone (Proyecto MIA) de la Maestria en Inteligencia Artificial Aplicada,
4ta cohorte (2026), Universidad de Las Americas (UDLA), Ecuador.

Titulo oficial: "Desarrollo de un Sistema Basado en Agentes de Inteligencia
Artificial y Aprendizaje Automatico para la Automatizacion, Optimizacion y
Personalizacion de los Servicios de Lina's Pet Salon".

## Objetivo general
Desarrollar un sistema multiagente conversacional que automatice la
atencion, cotizacion y agendamiento de citas del servicio de grooming de
Lina's Pet Salon (negocio de grooming canino en Quito, Ecuador), gestionado
por WhatsApp Business API, considerando restricciones operativas reales del
negocio, y manteniendo un paso de aprobacion humana antes de confirmar cada
cita con el cliente.

## Alcance funcional (lo que SI cubre)
- Comprension de intencion del mensaje del cliente (agendar, consultar,
  general).
- Respuestas fundamentadas en informacion real del negocio (RAG sobre
  base vectorial).
- Cotizacion estandarizada mediante clasificacion de imagen (tamano y
  tipo de pelaje de la mascota a partir de una foto).
- Gestion de agenda sobre un calendario digital exclusivo del negocio,
  con validacion automatica de restricciones operativas.
- Aprobacion humana obligatoria antes de confirmar cualquier cita.

## Fuera de alcance
- Hospedaje canino y linea de snacks (actividades secundarias del negocio).
- Identificacion de raza especifica o diagnostico de salud por imagen.
- Pagos, facturacion electronica, integracion con SRI.
- Optimizacion de rutas del servicio puerta a puerta.
- Automatizacion de Instagram (se mantiene manual).
- App movil nativa o portal web (todo ocurre en WhatsApp).

## Equipo
- Martin Nicolas Chavez Cadena ("Nico"): perfil mas tecnico del equipo.
  Owns el orquestador LangGraph, agente NLU, agente RAG, agente de
  cotizacion por imagen.
- Daniel Fernando Ocampo Zabala: WhatsApp Cloud API, Google Calendar,
  agente de agenda, corpus/ingestion vectorial.
- Daniel Sebastian Loza Caicedo: anonimizacion de datos, esquema de base
  de datos relacional, motor de reglas, metricas de evaluacion,
  coordinacion del piloto con la propietaria.

## Ventana de tiempo
16 semanas, 10 agosto - 27 noviembre 2026. Defensa formal: 15 noviembre 2026.
