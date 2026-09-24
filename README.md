<p align="center">
  <img src="logo_darsalud.png" alt="DarSalud" width="180">
</p>

<h1 align="center">Red Federal UGLs y Agencias – PAMI</h1>

<p align="center">
  Grafo interactivo con las <b>38 Unidades de Gestión Local (UGL)</b> de PAMI y sus <b>Agencias</b>,<br>
  con autoridades vigentes, domicilio, teléfono y ubicación en el mapa.
</p>

---

## ¿Qué es?

Una página web estática (publicada con GitHub Pages) que muestra la estructura territorial de PAMI como una red:

```
PAMI Nivel Central
 └── UGL (38)          ● círculo verde  (gris si todavía no tiene datos)
      └── Agencias     ◆ rombo naranja  (incluye CAPs y Bocas de Atención; más oscuro si no tiene titular vigente)
```

Al hacer clic en un nodo, el panel lateral muestra:

- **Ubicación y contacto:** dirección, localidad, teléfono y enlace a Google Maps.
- **Autoridades vigentes:** cargo, persona, fecha desde la que ocupa el cargo y norma que la designó.
- **Historial:** todas las designaciones, ceses y creaciones de dependencias publicadas en los boletines, con fecha.
- **Agencias de la UGL:** lista navegable; cada una abre su propia ficha.

Los datos de las autoridades se extraen automáticamente de los boletines oficiales y los domicilios salen del listado oficial de agencias de PAMI.

> ⚠️ Proyecto independiente, **no oficial**. La información proviene de fuentes públicas de PAMI y puede tener demoras o errores de extracción. Ante cualquier duda, verificar en [pami.org.ar](https://www.pami.org.ar).

---

## Funcionalidades

| Función | Detalle |
|---|---|
| **Intro animada** | Pantalla de presentación con el logo. Se cierra sola cuando el grafo terminó de cargar, o antes con un clic o `Esc`. |
| **Buscador rápido** (sobre el grafo) | Busca por UGL, número romano, localidad o Agencia y acerca la vista al nodo. Se navega con ↑ ↓ y Enter; la tecla `/` pone el cursor en el buscador. |
| **Buscador del panel** | Además de UGLs y Agencias, encuentra **personas** por nombre. |
| **Panel redimensionable** | Arrastrá el borde entre el grafo y el panel para cambiar el ancho. El navegador lo recuerda; con doble clic vuelve al tamaño original. |
| **Autoridades con fecha** | Cada cargo muestra desde cuándo está vigente y la resolución que lo designó. |
| **Historial** | Sección desplegable con todas las novedades de la UGL o de la Agencia, de la más reciente a la más antigua. |
| **Carga manual de datos** | Botón **Editar** en cada ficha para agregar o corregir dirección, teléfono, autoridades y agencias nuevas (ver más abajo). |
| **Filtro de la leyenda** | Muestra u oculta las Agencias. |
| **Responsive** | En el celular, el grafo queda arriba y el panel abajo. |

---

## Cómo funciona

```mermaid
flowchart LR
    BO[Boletines PAMI<br/>boletines_historicos/<br/>boletines_diarios/] -->|procesar_boletines.py<br/>lee el índice de cada PDF| D1[(datos_ugl.json<br/>autoridades vigentes<br/>+ historial)]
    XLS[listado-de-agencias.xlsx] -->|importar_listado_agencias.py| D2[(directorio_agencias.json<br/>domicilios)]
    ED[Botón Editar<br/>en la página] -->|Exportar| D3[(datos_manuales.json<br/>correcciones a mano)]
    D1 --> IDX[index.html]
    D2 --> IDX
    D3 --> IDX
    IDX --> G((Grafo))
```

### 1. Autoridades: `procesar_boletines.py`

Cada boletín de PAMI empieza con un **índice** donde cada resolución trae un resumen de una línea con formato fijo:

> *Designa y asigna al señor Esteban Maximiliano Herrera, las funciones de titular de la Agencia La Banda. UGL XIX - Santiago del Estero.*

El script lee **solo ese índice** (sin IA ni claves de API) y de cada resumen obtiene la acción, la persona, el cargo, la Agencia y la UGL. Después aplica todos los eventos **en orden cronológico**:

| Resumen del boletín | Efecto |
|---|---|
| *Designa y asigna / Asigna / Limita y asigna / Traslada y asigna ... las funciones de ...* | La persona pasa a ocupar el cargo. Si ya había alguien, lo reemplaza. |
| *Limita a ... las funciones de ...* | Cese: el cargo queda vacante. |
| *Limita y traslada a ...* | La persona deja todos sus cargos en esa UGL. |
| *Delega en ... la firma de ... la UGL* | Se registra como "Firma delegada de la UGL". |
| *Crea la Boca de Atención ...* | Se agrega la dependencia. |
| *Deja sin efecto la RESOL-...* | Se anula el evento de esa resolución. |

Reglas importantes:

- **La fecha es la del boletín** (nombre del archivo `dd-mm-aa.pdf`). Así la información siempre refleja la última publicación.
- Si una persona pasa a ser titular de otra Agencia de la misma UGL, deja la anterior (traslado).
- "Titular de la UGL" y "Titular de la Dirección Ejecutiva Local" se consideran el mismo cargo.
- El resultado se **recalcula completo** en cada corrida, así que es seguro correrlo las veces que haga falta. `cache_indices.json` guarda los índices ya leídos para que sea rápido.
- No se toman como autoridades las designaciones de personal ("para prestar servicios", "desempeñar tareas"), las ampliaciones de carga horaria ni las contrataciones.

### 2. Domicilios: `importar_listado_agencias.py`

Convierte el Excel oficial de agencias de PAMI en `directorio_agencias.json` (686 dependencias con domicilio, localidad y coordenadas). El index cruza cada Agencia con ese listado para completar su dirección y el enlace a Google Maps.

### 3. Datos cargados a mano: `datos_manuales.json`

Para lo que no figura en los boletines (teléfonos, un titular que todavía no salió publicado, una agencia nueva):

1. Abrí la ficha de la UGL o Agencia y tocá **Editar**.
2. Completá dirección, localidad, teléfono o autoridades; desde una UGL también podés **agregar una agencia**. Tocá **Guardar**.
3. El cambio se ve al instante y queda guardado **en tu navegador** (aparece con la etiqueta *manual*).
4. Para que lo vea todo el mundo, tocá **Exportar** (arriba, en el panel), y subí el archivo `datos_manuales.json` descargado al repositorio, reemplazando el anterior.

Los datos manuales tienen prioridad sobre los boletines y el listado oficial. **Importar** permite cargar un `datos_manuales.json` de otra persona y **Descartar** borra los cambios que todavía no exportaste.

### 4. Visualización: `index.html`

Página estática que lee los tres JSON y arma el grafo en el navegador con [vis-network](https://visjs.github.io/vis-network/docs/network/). Para depurar, en la consola del navegador: `modeloPAMI` muestra el árbol ya armado.

---

## Estructura del repositorio

```
├── index.html                    # Página: intro, grafo, buscadores, panel y editor
├── logo_darsalud.png             # Logo (intro)
├── datos_ugl.json                # Autoridades vigentes + historial (lo genera procesar_boletines.py)
├── directorio_agencias.json      # Domicilios oficiales (lo genera importar_listado_agencias.py)
├── datos_manuales.json           # Correcciones y agregados a mano (se exporta desde la página)
│
├── procesar_boletines.py         # Lee los boletines y genera datos_ugl.json
├── bot_diario_graffo.py          # Descarga el boletín del día y ejecuta procesar_boletines.py
├── importar_listado_agencias.py  # Excel oficial -> directorio_agencias.json
├── bot_directorio.py             # Scraper del buscador de agencias (opcional)
├── requirements.txt
│
├── boletines_historicos/         # PDFs dd-mm-aa.pdf (no hace falta subirlos al repo)
├── boletines_diarios/            # PDFs que descarga el bot diario
└── cache_indices.json            # Caché de lectura (se puede borrar sin problema)
```

`grafico.py` y `pdfs_procesados.txt` quedaron reemplazados por `procesar_boletines.py` y ya no se usan.

---

## Instalación y uso

### Ver el grafo en tu computadora

Los navegadores no dejan leer archivos JSON si abrís `index.html` con doble clic, por eso hace falta levantar un servidor local:

```bash
python -m http.server 8000
```

Después entrá a **http://localhost:8000**.

### Publicar en GitHub Pages

*Settings → Pages → Branch: `main` / carpeta `root`*. Cada `push` con JSON actualizados se refleja en la web.

### Actualizar los datos

Requiere **Python 3.10 o superior**; el bot diario además usa **Google Chrome**.

```bash
pip install -r requirements.txt

python procesar_boletines.py          # recalcula datos_ugl.json con todos los PDFs de las carpetas
python bot_diario_graffo.py           # descarga el boletín de hoy y recalcula
python importar_listado_agencias.py listado-de-agencias-.xlsx
```

Para que la actualización sea diaria, programá `bot_diario_graffo.py` en el **Programador de tareas** de Windows (o con `cron` en Linux) y después hacé `git commit` y `git push` de `datos_ugl.json`.

---

## Mantenimiento

| Situación | Qué hacer |
|---|---|
| Falta un dato que no sale en los boletines | Cargalo con **Editar** y exportá `datos_manuales.json`. |
| Una Agencia no muestra domicilio | No se encontró en el listado oficial con ese nombre. Cargalo a mano con **Editar**. |
| PAMI publicó un listado de agencias nuevo | Descargá el Excel y corré `importar_listado_agencias.py`. |
| Agregaste boletines viejos a la carpeta | Corré `procesar_boletines.py`: reordena todo por fecha solo. |

### Limitaciones conocidas

- **Teléfonos:** ni los boletines ni el listado oficial traen teléfonos; se cargan a mano.
- **Normas en bloque:** las resoluciones que asignan funciones "a los empleados de la UGL ..." traen el detalle en un anexo y no en el índice, por eso no se leen automáticamente.
- **Fecha de vigencia:** se usa la fecha de publicación del boletín, que puede diferir unos días de la fecha "a partir de" de la resolución.
- **Errores de tipeo en los boletines:** se toleran variantes comunes de escritura, pero un nombre muy mal escrito puede generar una agencia duplicada. Se corrige a mano.

---

## Tecnologías

[vis-network](https://visjs.github.io/vis-network/docs/network/) · HTML/CSS/JS sin frameworks · Python · PyMuPDF · Selenium · openpyxl

---

<p align="center"><i>Diseño y desarrollo: Leandro Sesto - 2026</i></p>
