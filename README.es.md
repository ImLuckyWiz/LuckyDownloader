# LuckyDownloader

Descarga VODs de Twitch (o cualquier enlace compatible con yt-dlp) y córtalos en partes por marcas de tiempo, con capítulos opcionales creados a partir de los clips de Twitch del VOD. Funciona en Windows, macOS y Linux.

*Read this in English: [README.md](README.md)*

---

## Descarga

Obtén la versión más reciente en la página de [Versiones](../../releases):

| Sistema | Archivo |
| --- | --- |
| Windows | `LuckyDownloader-Setup.exe` |
| macOS (Apple Silicon: M1, M2, M3, M4) | `LuckyDownloader-macos-arm64.dmg` |
| Linux (x86_64) | `LuckyDownloader-x86_64.AppImage`, `LuckyDownloader-linux-x86_64.tar.gz` |
| CLI sin interfaz gráfica | `LuckyDownloader-CLI-windows.zip`, `LuckyDownloader-CLI-macos-arm64.tar.gz`, `LuckyDownloader-CLI-linux-x86_64.tar.gz` |

### Instalación

- **Windows:** ejecuta el instalador. Se instala solo para tu usuario (no requiere permisos de administrador) y añade una entrada al menú Inicio. Ejecutar un instalador más reciente actualiza la instalación existente. Tus ajustes, historial y herramientas previas de LuckyTwitch se migran y conservan automáticamente.
- **macOS:** abre el `.dmg` y arrastra **LuckyDownloader** al acceso directo de **Aplicaciones**. Para actualizar, arrastra la nueva versión sobre la anterior y selecciona **Reemplazar** (cierra la aplicación primero).
- **Linux:** haz ejecutable el archivo AppImage (`chmod +x LuckyDownloader-x86_64.AppImage`) y ejecútalo (`./LuckyDownloader-x86_64.AppImage`). En Ubuntu 24.04+, si FUSE no está instalado, instala `libfuse2t64` (`sudo apt install libfuse2t64`) o extráelo (`./LuckyDownloader-x86_64.AppImage --appimage-extract`). También está disponible un archivo portátil comprimido (`LuckyDownloader-linux-x86_64.tar.gz`).

### Primer inicio

- **macOS:** la aplicación no está notarizada por Apple. Haz clic derecho → **Abrir** → **Abrir** (solo una vez). Si macOS indica que la aplicación está dañada, ejecuta `xattr -cr /Applications/LuckyDownloader.app` en la Terminal.
- **Windows:** SmartScreen puede mostrar una advertencia de editor desconocido. Haz clic en **Más información** → **Ejecutar de todas formas**.
- La aplicación necesita conexión a internet en su primer inicio: descarga **yt-dlp** y **ffmpeg** automáticamente. yt-dlp se mantiene actualizado de manera continua.
- **Migración desde LuckyTwitch:** tus ajustes, historial de descargas, lista de seguimiento y herramientas se copian automáticamente al nuevo directorio sin borrar los datos anteriores.

---

## Uso

1. Pega la URL o el ID de un VOD (o arrastra y suelta un enlace en la ventana) y presiona **Obtener información**.
2. Escribe los puntos de corte, por ejemplo `0:00 - 30:00 - 1:30:00 - end` (partes consecutivas). Usa `;` o una nueva línea para omitir intervalos vacíos: `0:00 - 30:00 ; 2:00:00 - end`. Los tiempos pueden ser `H:MM:SS`, `MM:SS`, segundos o `1h30m`. O utiliza la **Línea de tiempo** arriba del campo de texto: haz clic en las miniaturas para cortar, arrastra una línea de corte para moverla, haz clic derecho para eliminarla, haz clic en una parte para omitirla y doble clic en una barra de juego para convertir ese juego en su propia parte. La rueda del ratón amplía/reduce y **Deshacer** revierte la última edición. El texto y la línea de tiempo se sincronizan en todo momento.
3. Elige la estrategia de descarga (**Auto** selecciona la opción más eficiente: descargar el VOD completo y luego dividirlo, o descargar únicamente las partes necesarias), y luego inicia la tarea.

### Búsqueda de VODs (Pestaña Buscar) y Lista de seguimiento

En lugar de pegar un enlace puedes buscar un streamer: abre la pestaña **Buscar**, escribe el nombre y presiona Enter (o escribe/suelta el nombre del streamer directamente en la barra de URL de la pestaña Plan para ir a buscar). Elige un canal para ver sus VODs con miniaturas (emisiones pasadas, momentos destacados o subidas), luego haz doble clic en uno (o presiona **Usar este VOD**) para cargarlo en la pestaña Plan. Los streamers abiertos se recuerdan en **Streamers recientes**. La búsqueda requiere iniciar sesión con Twitch; si no has iniciado sesión, la pestaña muestra el botón **Iniciar sesión…**.

- **Lista de seguimiento:** haz clic en el botón de fijar en la cabecera de cualquier canal para añadirlo a tu lista de seguimiento. La aplicación comprueba periódicamente si hay emisiones más recientes y muestra una insignia de notificación en la pestaña Buscar. Nunca descarga nada de forma automática.
- **Historial de descargas:** presiona el botón **Historial** en la barra superior de comandos para ver tus descargas anteriores, con fecha, streamer, título, recuento de partes, calidad y carpeta de destino. Puedes volver a abrir cualquier carpeta o recargar el VOD en la pestaña Plan con un solo clic. Las tarjetas de VOD en Buscar y en la tira de Plan muestran una insignia `✓ Descargado` con la fecha.
- **Edición de títulos de emisión:** puedes editar el título de la emisión directamente en la **pestaña Plan** antes de añadir la descarga a la cola. El botón **Restablecer** restaura el título original de Twitch en cualquier momento.
- **Limpieza automática de títulos:** en **Opciones → Salida**, *Limpiar títulos automáticamente* elimina comandos de bots (`!links`, `!gsupps`), hashtags promocionales (`#ad`) y emoticonos para que los archivos tengan nombres limpios. Puedes desactivarlo si prefieres los títulos intactos.
- **Nombres limpios para descargas de una sola parte:** cuando una descarga tiene solo una parte, las etiquetas redundantes ` - part1` se omiten automáticamente tanto del nombre del archivo como de los metadatos de vídeo.

### Cola, Descargas en paralelo y Límite de velocidad

La pestaña **Cola y registro** administra y ejecuta las tareas en cola:

- **Descargas en paralelo:** en la pestaña Cola, elige cuántas tareas se ejecutan simultáneamente (desde **1 tarea** hasta **4 tareas en paralelo**). Las tareas se descargan en paralelo con carpetas temporales aisladas para evitar conflictos.
- **Cancelación selectiva:** si hay varias tareas en ejecución, seleccionar una fila específica y presionar **Cancelar actual** detiene únicamente esa descarga, permitiendo que las demás sigan ejecutándose.
- **Límite de ancho de banda:** establece un límite de velocidad opcional (**Sin límite**, **1 MB/s**, **2 MB/s**, **5 MB/s**, **10 MB/s**, **20 MB/s**) que se transfiere directamente a yt-dlp (`--limit-rate`) para no saturar tu conexión a internet.
- **Reordenar y reintentar:** reordena las descargas en espera con Subir / Bajar, o reintenta las tareas fallidas y canceladas con un clic.

### Interfaz y Barra de ventana personalizada

- **Idioma (Español):** LuckyDownloader está completamente traducido al inglés y al español. En el primer inicio detecta automáticamente el idioma de tu sistema operativo. Puedes cambiar de idioma en cualquier momento en **Opciones → Interfaz → Idioma**.
- **Barra de ventana oscura personalizada:** la ventana utiliza una barra de título oscura personalizada que coincide con la estética de la aplicación, con botones de minimizar, maximizar/restaurar y cerrar, arrastre fluido de ventana y recuperación de geometría. Para utilizar el marco de ventana nativo del sistema operativo, inicia la aplicación con el parámetro `--native-frame` o actívalo en los ajustes de Interfaz.

### Calidad y Solo audio (VODs de Twitch)

Al cargar un VOD de Twitch, aparece un selector de **Calidad** en la pestaña Plan:

- **Resoluciones:** `Fuente (1080p60)`, `720p60`, `480p`, etc.
- **Solo audio:** descarga únicamente la pista de sonido (formato `.m4a`), reduciendo drásticamente el tamaño del archivo y el tiempo de descarga.

---

## CLI y Google Colab

LuckyDownloader incluye una interfaz por línea de comandos (`cli.py`) completamente desacoplada de la interfaz gráfica, ideal para servidores y **Google Colab**:

```bash
# Instalar dependencias ligeras (sin PySide6)
pip install -r requirements-cli.txt

# Descargar secciones usando la sintaxis de puntos de corte
python cli.py "https://www.twitch.tv/videos/123456789" \
    --cuts "0:00:00 - 1:18:55 - end" \
    --out "./downloads" \
    --quality best
```

Consulta [docs/GOOGLE_COLAB.md](docs/GOOGLE_COLAB.md) para una guía paso a paso y celdas listas para Google Colab con montaje en Google Drive.

---

## Atajos de teclado

| Atajo | Acción |
| --- | --- |
| `Ctrl+L` | Enfocar la barra de URL |
| `Ctrl+1` – `Ctrl+4` | Cambiar entre pestañas (Buscar, Plan, Cola, Recientes) |
| `Ctrl+,` | Abrir Opciones |
| `Ctrl+Enter` | Añadir a la cola e iniciar descarga (en Plan) |
| `Ctrl+Shift+Enter` | Añadir a la cola sin iniciar (en Plan) |
| `F1` | Mostrar atajos de teclado |
| `F2` | Mostrar guía de bienvenida |

---

## Funciones principales y almacenamiento

- **Capítulos de clips y marcadores de juego:** Guarda archivos `.chapters.txt` y marcadores de juegos/audio silenciado en `.markers.json` junto a cada parte.
- **Panel CEP de Premiere Pro:** Importa marcadores, corta y elimina silencios/huecos directamente en la línea de tiempo (`premiere-plugin-cep/`).
- **Descarga y superposición de chat:** Descarga el chat (`.chat.json` / `.chat.txt`) y renderiza superposiciones transparentes con `TwitchDownloaderCLI`.
- **Enlaces profundos:** Soporta enlaces `luckydownloader://open` y `luckytwitch://open`.
- **Carpeta de descargas por defecto:** `Videos\LuckyDownloader` (Windows) o `~/Videos/LuckyDownloader` (macOS/Linux).
- **Datos y herramientas:** `%LOCALAPPDATA%\LuckyDownloader` (Windows), `~/Library/Application Support/LuckyDownloader` (macOS) o `~/.local/share/LuckyDownloader` (Linux).

---

## Ejecutar y compilar desde el código fuente

```bash
pip install -r requirements-dev.txt
python luckydownloader_qt.py
```

Para ejecutar las pruebas: `python -m pytest` (y `cd premiere-plugin-cep && npm test` para el panel CEP). Para compilar: `build_windows.bat`, `build_mac.sh` (Apple Silicon e Intel `x86_64`) o `build_linux.sh`.

---

## Licencia

LuckyDownloader se distribuye bajo los términos de la licencia MIT.
