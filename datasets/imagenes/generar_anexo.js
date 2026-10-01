/**
 * SCRUM-101 — Generación del anexo metodológico en Word.
 *   node generar_anexo.js
 */
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  PageBreak, Footer, PageNumber, LevelFormat, convertInchesToTwip,
} = require("docx");

const ANCHO = 9360; // 6,5" en DXA
const GRIS = "EFEFEF";
const AZUL = "1F3864";

const p = (texto, opts = {}) =>
  new Paragraph({
    spacing: { after: opts.after ?? 140, line: opts.line ?? 276 },
    alignment: opts.alignment,
    indent: opts.indent,
    border: opts.border,
    children: [new TextRun({ text: texto, size: opts.size ?? 22, font: "Calibri",
      bold: opts.bold, italics: opts.italics, color: opts.color })],
  });

const h = (texto, nivel) =>
  new Paragraph({
    heading: nivel,
    spacing: { before: 300, after: 160 },
    children: [new TextRun({ text: texto, bold: true, font: "Calibri",
      color: AZUL, size: nivel === HeadingLevel.HEADING_1 ? 30 : 25 })],
  });

const vineta = (texto) =>
  new Paragraph({
    numbering: { reference: "vinetas", level: 0 },
    spacing: { after: 90, line: 276 },
    children: [new TextRun({ text: texto, size: 22, font: "Calibri" })],
  });

const celda = (texto, { encabezado = false, ancho, alineacion } = {}) =>
  new TableCell({
    width: { size: ancho, type: WidthType.DXA },
    shading: encabezado ? { type: ShadingType.CLEAR, fill: GRIS, color: "auto" } : undefined,
    margins: { top: 70, bottom: 70, left: 110, right: 110 },
    children: [new Paragraph({
      alignment: alineacion,
      spacing: { after: 0, line: 252 },
      children: [new TextRun({ text: String(texto), bold: encabezado, size: 19, font: "Calibri" })],
    })],
  });

function tabla(encabezados, filas, anchos) {
  return new Table({
    columnWidths: anchos,
    width: { size: ANCHO, type: WidthType.DXA },
    rows: [
      new TableRow({
        tableHeader: true,
        children: encabezados.map((t, i) =>
          celda(t, { encabezado: true, ancho: anchos[i],
                     alineacion: i === 0 ? undefined : AlignmentType.CENTER })),
      }),
      ...filas.map((fila) =>
        new TableRow({
          children: fila.map((t, i) =>
            celda(t, { ancho: anchos[i],
                       alineacion: i === 0 ? undefined : AlignmentType.CENTER })),
        })),
    ],
  });
}

const pie = (texto) =>
  new Paragraph({
    spacing: { before: 60, after: 240 },
    children: [new TextRun({ text: texto, size: 17, italics: true, font: "Calibri", color: "555555" })],
  });

const hijos = [];
const add = (...x) => hijos.push(...x);

// ---------------------------------------------------------------- Portada
add(
  new Paragraph({ spacing: { before: 1800, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "PROYECTO MIA — LINA'S PET SALÓN", bold: true, size: 26, font: "Calibri", color: AZUL })] }),
  new Paragraph({ spacing: { before: 260, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Anexo metodológico", size: 40, bold: true, font: "Calibri" })] }),
  new Paragraph({ spacing: { before: 120, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Preparación y anonimización del dataset de imágenes", size: 30, font: "Calibri" })] }),
  new Paragraph({ spacing: { before: 60, after: 700 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Historia SCRUM-101 · Épica SCRUM-100 (Agente de Cotización por Imagen)", size: 22, italics: true, font: "Calibri" })] }),
  p("Maestría en Inteligencia Artificial Aplicada", { alignment: AlignmentType.CENTER, after: 40 }),
  p("Universidad de Las Américas", { alignment: AlignmentType.CENTER, after: 40 }),
  p("Daniel Loza C.", { alignment: AlignmentType.CENTER, bold: true, after: 40 }),
  p("20 de septiembre de 2026 · Versión 1.0", { alignment: AlignmentType.CENTER, after: 600, italics: true }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 0 },
    children: [new TextRun({ text: "Documento de trabajo. Las cifras de cobertura provienen del análisis del dataset público; las fotografías propias del negocio aún no han sido recogidas.", size: 19, italics: true, font: "Calibri", color: "7F7F7F" })] }),
  new Paragraph({ children: [new PageBreak()] }),
);

// ------------------------------------------------------------------- 1
add(h("1. Objeto de este anexo", HeadingLevel.HEADING_1));
add(p("La historia SCRUM-101 pide consolidar el Stanford Dogs Dataset con las fotografías propias del negocio y anonimizar cualquier dato personal antes de su uso en entrenamiento. Enunciada así, parece una tarea de manipulación de archivos. No lo es: entre el dataset público y lo que el negocio necesita hay tres brechas que ninguna operación de copiado resuelve, y que este anexo documenta junto con las decisiones tomadas para cerrarlas."));
add(vineta("Una brecha de etiquetas: Stanford Dogs está etiquetado por raza, y el tarifario de SCRUM-98 cobra por peso y por tipo de pelaje."));
add(vineta("Una brecha de dominio: Stanford Dogs contiene imágenes de catálogo obtenidas de la web, y el sistema recibirá fotografías tomadas con teléfono y recomprimidas por WhatsApp."));
add(vineta("Una brecha de volumen: la métrica comprometida en SCRUM-105 exige un conjunto de prueba de dominio real cuyo tamaño mínimo es calculable, y que hoy no existe."));
add(p("Este anexo deja constancia de cómo se resolvió cada una, qué queda abierto y qué no puede afirmarse todavía. Acompaña al paquete técnico ejecutable entregado en el mismo sprint."));

// ------------------------------------------------------------------- 2
add(h("2. Punto de partida: qué aporta y qué no aporta Stanford Dogs", HeadingLevel.HEADING_1));
add(h("2.1. Descripción de la fuente", HeadingLevel.HEADING_2));
add(p("El Stanford Dogs Dataset (Khosla, Jayadevaprakash, Yao y Fei-Fei, 2011) reúne 20 580 imágenes de 120 razas caninas, con una partición oficial de 12 000 imágenes de entrenamiento y 8 580 de prueba, y anotaciones de caja delimitadora para las imágenes de entrenamiento. Sus imágenes proceden de ImageNet (Deng et al., 2009), de donde hereda tanto sus propiedades visuales como sus condiciones de uso."));
add(h("2.2. Las etiquetas que trae no son las que el negocio necesita", HeadingLevel.HEADING_2));
add(p("El tarifario parametrizado definido en SCRUM-98 no cotiza por raza. Cotiza por tres clases de tamaño según peso vivo y por cuatro tipos de pelaje con factor multiplicativo:"));
add(tabla(
  ["Dimensión", "Clase", "Criterio", "Factor"],
  [
    ["Tamaño", "Pequeño", "0 – 9,0 kg", "—"],
    ["", "Mediano", "9,1 – 18,0 kg", "—"],
    ["", "Grande", "18,1 – 45,0 kg", "—"],
    ["Pelaje", "Corto", "manto raso", "1,00"],
    ["", "Doble / denso", "con subpelo", "1,15"],
    ["", "Largo", "manto largo", "1,20"],
    ["", "Rizado / lanudo", "manto rizado", "1,25"],
  ],
  [2100, 2300, 3060, 1900]));
add(pie("Tabla 1. Clases objetivo del dataset, tomadas literalmente del tarifario de SCRUM-98. Cualquier divergencia rompería la cadena SCRUM-101 → SCRUM-102 → SCRUM-103, por lo que el pipeline incorpora una verificación automática contra tarifario_v1.json."));
add(p("Traducir raza a estas clases exige una tabla de correspondencia explícita. Se construyó una, con las 120 razas, sus rangos de peso adulto según estándares de raza y su tipo de manto. Esa tabla es el aporte central de esta historia y se entrega como archivo versionado (config/mapeo_razas.csv)."));

add(h("2.3. Condiciones de uso: una limitación que debe declararse", HeadingLevel.HEADING_2));
add(p("El acuerdo de acceso de ImageNet restringe el uso de la base a fines de investigación no comercial y educativos. El trabajo de titulación cae dentro de ese alcance. Un eventual despliegue comercial del sistema en Lina's Pet Salón, en cambio, no: si el negocio decide operar el clasificador de forma productiva, el modelo deberá reentrenarse sobre fotografías propias, y Stanford Dogs quedará como lo que es aquí, una fuente de preentrenamiento y de referencia académica. Esta restricción se declara ahora, no al final, porque condiciona el diseño y no solo la redacción.", { }));

// ------------------------------------------------------------------- 3
add(h("3. Decisiones de diseño", HeadingLevel.HEADING_1));

add(h("D1. Dos variables independientes, no una clase conjunta", HeadingLevel.HEADING_2));
add(p("Se predicen tamaño y pelaje por separado, no una única clase de doce categorías. El tarifario los usa como factores independientes, y una clase conjunta exigiría cobertura simultánea de las doce celdas: inalcanzable para un negocio con alrededor de doce clientes fijos al mes."));

add(h("D2. La etiqueta derivada de la raza es una etiqueta débil, no verdad de campo", HeadingLevel.HEADING_2));
add(p("La raza induce una distribución de pesos, no un peso. Un Beagle adulto pesa entre 9 y 11,3 kg y por tanto atraviesa el corte de 9,0 kg del tarifario: su raza no determina su clase de tamaño. Tratar estas etiquetas como verdad de campo inflaría de forma artificial las métricas de SCRUM-105."));
add(p("En consecuencia, cada raza se declara con su rango de peso y el sistema marca como ambigua toda raza cuyo rango cruce un corte. Las razas ambiguas aportan etiqueta de pelaje pero no de tamaño. El criterio es conservador a propósito: es preferible perder datos que entrenar sobre etiquetas que se sabe equivocadas."));

add(h("D3. Exclusiones explícitas", HeadingLevel.HEADING_2));
add(p("Veintidós de las 120 razas se excluyen del dataset, por dos motivos distintos que conviene no confundir:"));
add(tabla(
  ["Motivo de exclusión", "Razas", "Justificación"],
  [
    ["Supera los 45 kg que cotiza el tarifario v1", "19", "El servicio no se ofrece; entrenar sobre ellas enseñaría una clase que el motor no sabe cotizar"],
    ["Cánido no doméstico", "3", "Dingo, dhole y licaón provienen de la jerarquía WordNet de ImageNet; no son clientes posibles de un salón"],
  ],
  [3400, 1200, 4760]));
add(pie("Tabla 2. Exclusiones. Las tres últimas razas son un recordatorio de que Stanford Dogs no fue construido para este problema: heredó su taxonomía de ImageNet, no del negocio."));

add(h("D4. El conjunto de prueba es exclusivamente de dominio real", HeadingLevel.HEADING_2));
add(p("Es la decisión de mayor consecuencia del anexo. Stanford Dogs y las fotografías que llegan por WhatsApp no pertenecen al mismo dominio: las primeras están bien encuadradas, bien iluminadas y a menudo corresponden a ejemplares de exposición; las segundas vienen recomprimidas por el canal, con el animal en movimiento, a contraluz o sobre fondos estampados. Hendrycks y Dietterich (2019) documentan caídas sustanciales de exactitud ante desenfoque, ruido y compresión JPEG, que son precisamente las degradaciones del canal de despliegue."));
add(p("Por ello el reparto es asimétrico: el entrenamiento admite Stanford Dogs, la evaluación no. El umbral de F1 macro ≥ 0,85 comprometido en SCRUM-105 solo es defendible medido sobre fotografías reales del negocio jamás vistas. Medido sobre Stanford Dogs sería un número alto y sin significado."));
add(p("Como paliativo —no como sustituto— el pipeline incorpora aumentación que replica la degradación del canal: reescalado del lado mayor a 1 600 px, recompresión JPEG entre calidad 65 y 85, desenfoque gaussiano, variación de exposición y recortes descentrados. Reduce la brecha de dominio; no la cierra.", {}));

add(h("D5. La partición agrupa por mascota, no por imagen", HeadingLevel.HEADING_2));
add(p("Con una docena de clientes fijos, una misma mascota aparecerá muchas veces en el corpus. Si dos fotografías del mismo animal caen en lados opuestos de la partición, el modelo reconoce al individuo y la métrica se infla. La partición se hace por seudónimo de mascota —el mismo que usa el dataset de SCRUM-63—, con semilla 42 para que ambos conjuntos sean comparables y reproducibles."));

add(h("D6. Anonimización en dos capas", HeadingLevel.HEADING_2));
add(p("Una fotografía de una mascota no es por sí misma un dato personal del cliente; sí lo son los metadatos que la acompañan y las personas que puedan aparecer en el encuadre. El tratamiento se apoya en la Ley Orgánica de Protección de Datos Personales del Ecuador (LOPDP, R.O. Supl. 459, 2021), que distingue seudonimización de disociación."));
add(vineta("Metadatos: la imagen se reescribe volcando únicamente la matriz de píxeles, de modo que no sobreviva ningún segmento EXIF, XMP o IPTC. Antes de descartarlos se deja constancia de qué campos sensibles existían —GPSInfo en particular, que en una foto tomada en el domicilio del cliente equivale a su dirección—, porque el registro de actividades de tratamiento debe poder demostrar qué se recibió y qué se eliminó."));
add(vineta("Identificadores: seudonimización determinista HMAC-SHA256 con sal secreta, el mismo mecanismo y la misma sal de SCRUM-63. Esto permite enlazar la fotografía de una mascota con la conversación de WhatsApp del mismo cliente, agrupar por individuo para evitar fuga, y corregir etiquetas sin re-identificar. La anonimización plena se alcanza destruyendo la sal al cierre del proyecto."));
add(p("La sal no se versiona: se lee de la variable de entorno MIA_SAL_SEUDONIMO y, si falta, el pipeline se detiene. Es preferible no producir dataset a producir uno con seudónimos reproducibles por terceros. La revisión manual del 100 % de las fotografías propias es paso obligatorio del protocolo, no opcional, y el verificador de partición bloquea el cierre de la historia si alguna fotografía no la registra."));

add(h("D7. Deduplicación perceptual", HeadingLevel.HEADING_2));
add(p("Las fotografías de Instagram del negocio suelen reciclarse: la misma imagen republicada con otro recorte. Se aplica hash perceptual (pHash, 64 bits) con umbral de distancia de Hamming de 5, valor habitual para considerar dos imágenes la misma fotografía tras recompresión. Es el equivalente, en el dominio visual, al control de casi-duplicados que SCRUM-63 aplicó al corpus textual."));

// ------------------------------------------------------------------- 4
add(new Paragraph({ children: [new PageBreak()] }));
add(h("4. Resultados del análisis de cobertura", HeadingLevel.HEADING_1));
add(p("Aplicada la tabla de correspondencia a las 120 razas, la cobertura que Stanford Dogs realmente aporta es sensiblemente menor que sus 20 580 imágenes sugieren."));
add(tabla(
  ["Resultado del mapeo", "Razas", "% del total"],
  [
    ["Con etiqueta de tamaño utilizable", "70", "58,3 %"],
    ["Solo utilizables para pelaje (tamaño ambiguo)", "28", "23,3 %"],
    ["Excluidas", "22", "18,3 %"],
    ["Total", "120", "100 %"],
  ],
  [4600, 2200, 2560]));
add(pie("Tabla 3. Aporte efectivo del dataset público. Solo el 58,3 % de las razas produce una etiqueta de tamaño defendible."));

add(h("4.1. La clase mediana es el hueco crítico", HeadingLevel.HEADING_2));
add(tabla(
  ["Clase de tamaño", "Razas con etiqueta utilizable", "Imágenes estimadas"],
  [
    ["Pequeño (0 – 9,0 kg)", "27", "≈ 4 600"],
    ["Mediano (9,1 – 18,0 kg)", "6", "≈ 1 030"],
    ["Grande (18,1 – 45,0 kg)", "37", "≈ 6 350"],
  ],
  [3400, 3000, 2960]));
add(pie("Tabla 4. Distribución por tamaño. Las imágenes estimadas usan el promedio de 171,5 imágenes por raza del dataset; el pipeline calcula los conteos exactos cuando las carpetas están presentes."));
add(p("Seis razas de 120 caen íntegramente en la franja mediana. No es un defecto del mapeo sino de la realidad cinológica: los rangos de peso de las razas medianas son anchos y cruzan los cortes del tarifario con más frecuencia que los de razas muy pequeñas o muy grandes. El efecto práctico es serio, porque la franja mediana es la franja de precio intermedia, aquella en la que un error de clasificación traslada la cotización a un escalón equivocado en cualquiera de las dos direcciones."));
add(p("Consecuencia operativa, recogida en el protocolo de captura: las fotografías de perros medianos son las de mayor valor marginal para el proyecto y deben solicitarse primero."));

add(h("4.2. Cobertura por pelaje", HeadingLevel.HEADING_2));
add(tabla(
  ["Tipo de pelaje", "Factor del tarifario", "Razas no excluidas"],
  [
    ["Corto", "1,00", "28"],
    ["Doble / denso", "1,15", "35"],
    ["Largo", "1,20", "27"],
    ["Rizado / lanudo", "1,25", "8"],
  ],
  [3400, 3000, 2960]));
add(pie("Tabla 5. Distribución por pelaje. La clase peor representada es la de factor más alto."));
add(p("El pelaje rizado o lanudo cuenta con ocho razas, la cobertura más baja de la dimensión, y es precisamente el que lleva el recargo mayor del tarifario. Un clasificador que falle sistemáticamente en esta clase produciría cotizaciones por debajo del costo real del servicio, un error asimétrico: perjudica al negocio y no al cliente, por lo que no se manifestaría como queja y podría pasar inadvertido durante meses."));

add(h("4.3. Hallazgo: la taxonomía de pelajes no cubre el pelo duro", HeadingLevel.HEADING_2));
add(p("Dieciocho de las razas no excluidas tienen manto duro o de arranque —terriers y schnauzers, fundamentalmente—, que no corresponde a ninguna de las cuatro categorías del tarifario v1. Se asignaron de forma provisional a «doble» y quedaron marcadas en la columna pelaje_observacion del mapeo."));
add(p("La observación excede el alcance de SCRUM-101 y se traslada a SCRUM-98: el pelo duro exige técnica de stripping y es de los más costosos en tiempo de grooming, de modo que agruparlo con el manto doble subestima su costo. La decisión de incorporar o no una quinta categoría corresponde a la propietaria, y este anexo se limita a documentar que la taxonomía vigente tiene ese punto ciego.", { }));

// ------------------------------------------------------------------- 5
add(new Paragraph({ children: [new PageBreak()] }));
add(h("5. Volumen mínimo exigible y su trazabilidad", HeadingLevel.HEADING_1));
add(p("SCRUM-105 compromete un F1 macro ≥ 0,85. Una métrica sin intervalo de confianza no es un resultado sino una anécdota, criterio ya aplicado en SCRUM-63 al rechazar un conjunto de prueba de 56 casos como estimación estable. Para una proporción p en torno a 0,85, la semiamplitud del intervalo de Wald al 95 % es 1,96 · √(p(1−p)/n); despejando n para una semiamplitud objetivo se obtiene el tamaño mínimo del conjunto de prueba por clase."));
add(tabla(
  ["Semiamplitud del IC 95 %", "n mínimo por clase", "Conjunto de prueba (4 clases)", "Fotografías propias totales"],
  [
    ["± 5 puntos", "196", "784", "1 960"],
    ["± 10 puntos", "49", "196", "490"],
    ["± 15 puntos", "22", "88", "220"],
    ["± 20 puntos", "13", "52", "130"],
  ],
  [2600, 2100, 2500, 2160]));
add(pie("Tabla 6. Volumen exigible según la precisión que se quiera reportar. La última columna asume que el conjunto de prueba es el 40 % de las fotografías propias recogidas. Las cifras las calcula el módulo reporte.py; no están fijadas a mano."));
add(p("La lectura es incómoda y por eso conviene hacerla explícita: afirmar «F1 = 0,87» con un margen de diez puntos exige alrededor de 490 fotografías propias, cifra exigente para un negocio con doce clientes fijos al mes. El mínimo defendible —130 fotografías, margen de veinte puntos— sigue siendo un resultado publicable siempre que el margen se declare. Lo que no es defendible es reportar la cifra puntual sin decir sobre cuántos casos se midió."));
add(p("La decisión sobre qué nivel adoptar no corresponde a esta historia: corresponde a SCRUM-105 y debe tomarse antes de entrenar, no después de ver los resultados."));

// ------------------------------------------------------------------- 6
add(h("6. El problema de la escala y sus consecuencias de diseño", HeadingLevel.HEADING_1));
add(p("Una fotografía sin referencia de tamaño conocida no contiene la información necesaria para estimar la talla absoluta de un animal: un perro pequeño cerca de la cámara y uno grande lejos ocupan la misma superficie de imagen. Un observador humano resuelve la ambigüedad porque reconoce la raza y conoce su peso típico; el clasificador, entrenado sobre etiquetas derivadas de la raza, hará exactamente lo mismo. Es decir, estará reconociendo apariencia racial y consultando un prior de peso, no midiendo."));
add(p("Esto no invalida el enfoque, pero fija su techo y lo alinea con el principio que SCRUM-98 ya había establecido: el sistema no debe pretender adivinar mejor que la propietaria a partir de la misma fotografía. De ahí dos decisiones:"));
add(vineta("El protocolo de captura exige una referencia de escala —una hoja A4 apoyada en el piso junto al animal— en todas las fotografías de cuerpo entero, y el manifiesto registra si estaba presente. Permite, más adelante, comparar el desempeño con y sin referencia."));
add(vineta("La salida del clasificador alimenta la banda de confianza de SCRUM-98 como un atributo más, no como una certeza. Una clasificación de tamaño obtenida sin referencia de escala debe seguir contando como atributo no declarado a efectos del cálculo de incertidumbre."));
add(p("La segunda decisión tiene una implicación que conviene anticipar para SCRUM-103: si el clasificador de imagen no retira incertidumbre de la banda, el Agente de Cotización por Imagen no reduce por sí solo la amplitud del rango de precio; lo que hace es ahorrarle a la clienta responder preguntas, a costa de una estimación menos firme. Conviene que el informe final no presente la cotización por imagen como una mejora de precisión sino como una mejora de fricción conversacional."));

// ------------------------------------------------------------------- 7
add(h("7. Verificación", HeadingLevel.HEADING_1));
add(p("El paquete incorpora 28 pruebas automatizadas, nombradas por criterio de aceptación siguiendo la convención adoptada en SCRUM-98. Todas se superan en la ejecución del 20 de septiembre de 2026."));
add(tabla(
  ["Criterio de aceptación", "Pruebas", "Qué se verifica"],
  [
    ["CA1 — Consolidación de fuentes", "4", "Las 120 razas están mapeadas; una raza presente en disco y ausente de la tabla detiene el pipeline"],
    ["CA2 — Anonimización previa al uso", "5", "Los metadatos desaparecen; el seudónimo es determinista y no reversible sin sal; sin sal el pipeline se detiene"],
    ["CA3 — Etiquetas conformes al tarifario", "5", "Los cortes de peso replican SCRUM-98; las razas que cruzan un corte se marcan ambiguas"],
    ["CA4 — Partición reproducible y sin fuga", "4", "Misma semilla, misma partición; una fuga inyectada se detecta"],
    ["CA5 — El test refleja el dominio de despliegue", "5", "Stanford Dogs nunca llega a test; la contaminación se detecta"],
    ["CA6 — Cobertura documentada", "5", "El mínimo por clase se calcula, no se fija; la brecha se expresa en fotografías a capturar"],
  ],
  [3100, 1100, 5160]));
add(pie("Tabla 7. Cobertura de pruebas por criterio de aceptación."));
add(p("Además, el pipeline dispone de un modo de simulación (--simular) que ejecuta la partición, los controles de fuga y el reporte de cobertura sobre un manifiesto sintético. Permite demostrar la cadena completa en la revisión de sprint sin disponer todavía de las fotografías reales."));

// ------------------------------------------------------------------- 8
add(new Paragraph({ children: [new PageBreak()] }));
add(h("8. Limitaciones declaradas", HeadingLevel.HEADING_1));
add(p("Se enuncian aquí, y no en el capítulo de conclusiones, porque condicionan la lectura de todo lo anterior:"));
add(vineta("Ninguna cifra de este anexo es un resultado del proyecto. Son propiedades del dataset público y cálculos de diseño. El dataset propio no existe todavía."));
add(vineta("Los rangos de peso por raza provienen de estándares de raza, no de mediciones del negocio. Su función es descartar razas ambiguas y estimar cobertura, nunca sustituir el peso declarado por el cliente, que es el dato que el tarifario usa en producción."));
add(vineta("Los nombres de las cuatro clases de pelaje deben contrastarse contra tarifario_v1.json en cuanto el archivo esté disponible. El pipeline incorpora la verificación automática; hasta ejecutarla, la correspondencia es una suposición razonada."));
add(vineta("La eliminación de fotografías a solicitud de un cliente retira los datos del conjunto, pero un modelo ya entrenado no puede desaprenderlas sin reentrenamiento completo. El consentimiento informado recoge esta salvedad de forma explícita."));
add(vineta("El texto del consentimiento fue redactado siguiendo la LOPDP y su reglamento, pero requiere revisión de un profesional del derecho antes de usarse con clientes reales. El responsable del tratamiento es el negocio, no la universidad."));

// ------------------------------------------------------------------- 9
add(h("9. Bloqueantes y decisiones pendientes", HeadingLevel.HEADING_1));
add(tabla(
  ["Bloqueante", "Depende de", "Impacto si no se resuelve"],
  [
    ["Fotografías propias del negocio (Instagram y dispositivo de la propietaria)", "Propietaria", "Sin conjunto de prueba de dominio real, la métrica de SCRUM-105 no es defendible"],
    ["Consentimiento informado firmado por los clientes", "Propietaria / revisión legal", "Las fotografías no pueden usarse"],
    ["tarifario_v1.json para verificar los nombres de clase", "SCRUM-98 (cerrado, pendiente de compartir el archivo)", "Riesgo de incompatibilidad entre el clasificador y el motor de cotización"],
    ["Decisión sobre el margen de error admisible de la métrica", "Equipo y tutora", "Determina cuántas fotografías hay que recoger; debe decidirse antes de entrenar"],
    ["Decisión sobre una quinta categoría de pelaje (pelo duro)", "Propietaria / SCRUM-98", "Subestimación del costo del grooming en terriers y schnauzers"],
  ],
  [3300, 2400, 3660]));
add(pie("Tabla 8. Estado de bloqueantes al 20 de septiembre de 2026."));
add(p("El primero es el crítico. SCRUM-101 vence el 27 de septiembre y SCRUM-102 —el entrenamiento, asignado a otro integrante— vence el 4 de octubre. El pipeline queda listo para ejecutarse en cuanto lleguen las fotografías, de modo que la dependencia no bloquea el trabajo de diseño; sí bloquea la obtención de un dataset final y, por tanto, el cierre efectivo de la historia."));

// ------------------------------------------------------------------- 10
add(h("10. Referencias", HeadingLevel.HEADING_1));
const refs = [
  "Deng, J., Dong, W., Socher, R., Li, L.-J., Li, K. y Fei-Fei, L. (2009). ImageNet: A large-scale hierarchical image database. En IEEE Conference on Computer Vision and Pattern Recognition (pp. 248–255).",
  "Hendrycks, D. y Dietterich, T. (2019). Benchmarking neural network robustness to common corruptions and perturbations. En International Conference on Learning Representations (ICLR).",
  "Khosla, A., Jayadevaprakash, N., Yao, B. y Fei-Fei, L. (2011). Novel dataset for fine-grained image categorization. En First Workshop on Fine-Grained Visual Categorization, IEEE Conference on Computer Vision and Pattern Recognition. Colorado Springs, CO.",
  "Ley Orgánica de Protección de Datos Personales. Registro Oficial Suplemento 459 de 26 de mayo de 2021. Quito, Ecuador.",
  "Reglamento General a la Ley Orgánica de Protección de Datos Personales. Quito, Ecuador.",
  "Sculley, D., Holt, G., Golovin, D., Davydov, E., Phillips, T., Ebner, D., Chaudhary, V., Young, M., Crespo, J.-F. y Dennison, D. (2015). Hidden technical debt in machine learning systems. En Advances in Neural Information Processing Systems (NIPS), 28, 2503–2511.",
  "Stanford Vision Lab. (s. f.). Stanford Dogs Dataset. http://vision.stanford.edu/aditya86/ImageNetDogs/",
  "Princeton University y Stanford Vision Lab. (s. f.). ImageNet — Terms of access. https://image-net.org/accessagreement",
];
refs.forEach((r) => add(new Paragraph({
  spacing: { after: 140, line: 276 },
  indent: { left: convertInchesToTwip(0.5), hanging: convertInchesToTwip(0.5) },
  children: [new TextRun({ text: r, size: 21, font: "Calibri" })],
})));

// ------------------------------------------------------------------ Doc
const doc = new Document({
  numbering: {
    config: [{
      reference: "vinetas",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "•",
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: convertInchesToTwip(0.35), hanging: convertInchesToTwip(0.2) } } },
      }],
    }],
  },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "Proyecto MIA · Anexo metodológico SCRUM-101 · ", size: 17, color: "808080", font: "Calibri" }),
                     new TextRun({ children: [PageNumber.CURRENT], size: 17, color: "808080", font: "Calibri" })],
        })],
      }),
    },
    children: hijos,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  const salida = process.argv[2] || "Anexo_Metodologico_SCRUM101.docx";
  fs.writeFileSync(salida, buf);
  console.log("Escrito:", salida, `(${(buf.length / 1024).toFixed(0)} KB)`);
});
