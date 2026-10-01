# Protocolo de captura estructurada de fotografías

**Proyecto MIA — Lina's Pet Salón · Historia SCRUM-101**
Versión 1.0 · 20 de septiembre de 2026

---

## 1. Para qué sirve esto

El sistema va a estimar el tamaño y el tipo de pelaje de una mascota a partir de
una fotografía, y de esa estimación depende el precio que se le ofrece al
cliente. Para que aprenda a hacerlo hace falta un conjunto de fotografías que se
parezcan a las que enviarán los clientes por WhatsApp, y que vengan acompañadas
del peso real y del tipo de pelaje.

Las fotografías del dataset público que se está usando como base (Stanford Dogs)
son imágenes de catálogo: perros de exposición, bien iluminados y bien
encuadrados. No se parecen a lo que llega por WhatsApp. Por eso las fotografías
que se capturen con este protocolo son las únicas que se usarán para **medir**
si el sistema funciona.

---

## 2. Lo primero: la referencia de escala

**Este es el punto más importante del protocolo.**

En una fotografía sin nada conocido al lado, no hay forma de saber si el perro
mide 25 o 60 centímetros: un Chihuahua cerca de la cámara y un Labrador lejos
ocupan lo mismo en la imagen. Una persona lo resuelve porque reconoce la raza y
sabe cuánto pesa esa raza; una fotografía por sí sola no lleva esa información.

Por eso, en **todas** las fotografías de cuerpo entero debe aparecer un objeto
de tamaño conocido junto a la mascota, apoyado en el mismo piso:

- **Recomendado: una hoja de papel A4** (21 × 29,7 cm), puesta en el suelo junto
  a las patas del animal. Es gratis, es plana y mide siempre lo mismo.
- Alternativas válidas: una botella de agua de 500 ml de pie, o una regla de
  30 cm.
- No sirven: la mano de una persona, un juguete, un mueble.

Si por alguna razón no se pudo poner la referencia, la foto igual sirve — pero
hay que marcarla con `escala_presente = 0` en la hoja de registro.

---

## 3. Cómo tomar cada fotografía

### Posición del animal

- De pie, con las cuatro patas apoyadas en el piso.
- Nunca en brazos, nunca sobre una mesa, nunca echado.

### Posición de la cámara

- A la **altura del pecho del animal**, no desde arriba. Fotografiar desde
  arriba achata al perro y hace que uno grande parezca mediano.
- A unos dos metros de distancia. Usar zoom si hace falta acercarse, no caminar
  hacia el animal.
- Cámara en horizontal.

### Tres fotografías por mascota

| # | Toma | Qué debe verse |
|---|------|----------------|
| 1 | **Perfil completo** | Todo el cuerpo de lado, de la nariz a la cola, con la hoja A4 en el piso |
| 2 | **Frontal completa** | Todo el cuerpo de frente, con la hoja A4 en el piso |
| 3 | **Detalle del manto** | Primer plano del lomo y el costado, para ver la textura del pelo |

### Fondo e iluminación

- Fondo lo más liso posible: una pared clara, el piso vacío. Evitar alfombras
  estampadas, cortinas floreadas, otros animales en el cuadro.
- Luz natural indirecta. Nunca a contraluz (con la ventana detrás del animal).
- No usar flash: aplana el pelo y cambia el color.

### Personas en el cuadro

**No deben aparecer personas**, ni siquiera parcialmente (manos, pies, piernas).
Dos razones: una cara identificable convierte la foto en un dato personal
sujeto a la LOPDP, y una persona en el cuadro confunde al modelo sobre cuál es
el sujeto de la imagen.

Si el animal no se queda quieto sin que alguien lo sostenga, tomar la foto igual
y anotarlo en la columna `observaciones`; en el procesamiento se recortará o se
difuminará a la persona.

---

## 4. Qué anotar de cada mascota

Por cada mascota fotografiada hay que llenar una fila en `etiquetas.csv`. Los
cuatro primeros datos no son opcionales: son exactamente los cuatro atributos
que el motor de cotización usa para estrechar la banda de precio (SCRUM-98).

| Columna | Qué poner | Por qué importa |
|---------|-----------|-----------------|
| `archivo` | nombre exacto del archivo de foto | enlaza la foto con sus datos |
| `mascota` | nombre de la mascota o teléfono del dueño | agrupa las fotos del mismo animal |
| `peso_kg` | **peso real, en balanza**, con un decimal | es la etiqueta de tamaño; estimarlo a ojo arruina el dataset |
| `pelaje` | `corto`, `doble`, `largo` o `rizado` | es la etiqueta de pelaje |
| `estado_manto` | `normal`, `enredado` o `muy_enredado` | quita 7 puntos de incertidumbre al precio |
| `comportamiento` | `tranquilo`, `inquieto` o `dificil` | quita 3 puntos de incertidumbre al precio |
| `escala_presente` | `1` si la foto tiene la hoja A4, `0` si no | permite saber qué fotos sirven para estimar talla absoluta |
| `revision_manual` | `1` cuando alguien ya revisó que no hay personas ni datos visibles | obligatorio antes de usar la foto |
| `observaciones` | texto libre | cualquier cosa rara |

**El peso debe medirse en balanza.** Si no hay balanza para mascotas: pesarse la
persona sola, luego con el animal en brazos, y restar. Anotar el resultado con
un decimal.

---

## 5. Qué mascotas priorizar

No todas las fotos valen lo mismo. El análisis de cobertura mostró dos huecos
graves, y las fotos que los llenen son las más valiosas:

1. **Perros medianos (entre 9,1 y 18 kg).** Es la clase peor cubierta con
   diferencia: de las 120 razas del dataset público, solo 6 caen íntegramente en
   este rango. Es además la franja de precio intermedia, la que más se equivoca
   si el modelo falla.
2. **Perros de pelaje rizado o lanudo** (caniches, bichones, mestizos de pelo
   lanudo). Solo 8 razas del dataset público tienen este pelaje, y es el que
   lleva el recargo más alto del tarifario (1,25).

En cambio, fotos de perros pequeños de pelo corto ya hay de sobra en la base
pública. **Si hay que elegir a qué cliente pedirle fotos, empezar por los perros
medianos y por los de pelo rizado.**

---

## 6. Cuántas fotografías hacen falta

Para poder afirmar que el clasificador acierta el 85 % de las veces con un
margen de error de ±10 puntos, hacen falta cerca de **50 fotografías por clase
en el conjunto de prueba**, lo que se traduce en unas **490 fotografías propias
en total**.

Esa cifra es exigente para un negocio con ~12 clientes fijos al mes, y hay que
decirlo con claridad en vez de descubrirlo al final. Las opciones son tres, y la
decisión es del equipo junto con la propietaria:

| Opción | Fotos propias necesarias | Margen de error de la métrica |
|--------|--------------------------|-------------------------------|
| Recoger todo lo posible durante 3 meses | ~490 | ±10 puntos |
| Alcance intermedio | ~220 | ±15 puntos |
| Mínimo defendible | ~130 | ±20 puntos |

La tercera opción sigue siendo un resultado publicable **siempre que el margen
se declare**. Lo que no es defendible es reportar "F1 = 0,87" sin decir sobre
cuántos casos se midió.

---

## 7. Cómo entregar las fotografías

1. Copiar todas las fotos a una carpeta llamada `captura_<fecha>`.
2. Llenar `etiquetas.csv` con una fila por fotografía.
3. Entregar la carpeta y el CSV juntos.
4. **No renombrar los archivos después de llenar el CSV**: el enlace se rompe.

Las fotografías se procesan con el pipeline de SCRUM-101, que elimina todos los
metadatos (incluida la ubicación GPS, que en una foto tomada en el domicilio del
cliente equivale a su dirección) y sustituye el nombre del dueño por un código
irreversible.
