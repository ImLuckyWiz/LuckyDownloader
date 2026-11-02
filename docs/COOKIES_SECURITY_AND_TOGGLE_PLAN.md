# Plan de Seguridad, Ámbito y Control de Cookies por Video (Cookie Scope & Per-Video Toggle)

Este documento describe la especificación técnica, diseño de interfaz y plan de implementación para limitar el envío de cookies del navegador únicamente a los sitios que realmente lo requieren, incorporando un control explícito por video y por lista de reproducción.

---

## 1. Contexto y Motivación

Actualmente, cuando el usuario selecciona un navegador en **Opciones > Herramientas > Cookies del navegador** (por ejemplo, *Firefox* o *Chrome*):
- Dicha configuración opera como un interruptor global.
- Al inspeccionar (`get_source_info`) o descargar cualquier enlace (`download_full`, `run_ytdlp`, `build_generic_download_args`), el parámetro `--cookies-from-browser <browser>` se envía de manera incondicional a `yt-dlp`.

### Riesgos identificados
1. **Privacidad y Seguridad:** Si el usuario descarga contenido de sitios para adultos (ej. Pornhub) o enlaces web arbitrarios, `yt-dlp` intenta acceder a la base de datos de cookies de ese navegador para ese dominio. No hay motivo para compartir sesiones ni cookies en estos sitios.
2. **Falta de control granular:** El usuario no puede elegir descargar un video específico *sin* cookies a menos que vaya a la pestaña de Opciones y desactive la opción globalmente.
3. **Comportamiento no deseado en sitios no autenticados:** Sitios públicos o APIs que no requieren autenticación pueden comportarse de manera inesperada si reciben sesiones activas del navegador.

---

## 2. Objetivos Principales

1. **Privacidad por defecto:** Las cookies nunca deben enviarse a sitios para adultos o dominios arbitrarios sin autorización expresa.
2. **Ámbito seguro (Safe Domain Scope):** Solo las plataformas conocidas que típicamente imponen muros de inicio de sesión o restricciones de edad (`YouTube`, `TikTok`, `Instagram`, `Twitter/X`) deben ser elegibles por defecto para recibir cookies del navegador.
3. **Control explícito por video (Per-Video Toggle):** Agregar un toggle en la tarjeta de detalles del video (Pestaña Plan) y en el diálogo de listas para que el usuario pueda activar o desactivar las cookies para esa descarga puntual.
4. **Inspección no invasiva:** No enviar cookies durante la obtención inicial de información si el dominio no pertenece al ámbito seguro. Si un video bloqueado requiere inicio de sesión, informar y permitir reintentar de forma segura.

---

## 3. Especificación Técnica y Arquitectura

### 3.1. Módulo de Ámbito de Cookies (`core/cookie_scope.py`)
Crear funciones auxiliares para validar si una URL o proveedor es elegible para cookies:
- **Dominios permitidos por defecto (`DEFAULT_COOKIE_DOMAINS`):**
  - YouTube: `youtube.com`, `youtu.be`, `music.youtube.com`
  - TikTok: `tiktok.com`
  - Instagram: `instagram.com`
  - Twitter / X: `twitter.com`, `x.com`
- **Función `is_cookie_eligible(url: str, scope_mode: str = "known_only") -> bool`:**
  - Extrae el host de la URL (normalizando subdominios).
  - Si `scope_mode == "known_only"`: retorna `True` si el host coincide con `DEFAULT_COOKIE_DOMAINS`; `False` en caso contrario.
  - Si `scope_mode == "all"`: retorna `True` para cualquier URL HTTP/HTTPS.
- **Función `resolve_cookies_for_request(url: str, cookies_browser: str | None, scope_mode: str, explicit_enabled: bool | None = None) -> str | None`:**
  - Determina el string del navegador (`"firefox"`, `"chrome"`, etc.) o `None` a pasar a `yt-dlp`.

### 3.2. Configuración en Opciones (`core/settings.py` & `qt_ui/tabs/options.py`)
- Nueva clave de configuración:
  - `cookies_scope`: `"known_only"` (por defecto) | `"all"`
- En la interfaz de **Opciones > Herramientas**:
  - Selector **Ámbito de cookies:**
    - `Solo plataformas conocidas (YouTube, TikTok, Instagram, X)` (Recomendado)
    - `En todos los sitios soportados`

### 3.3. Control en la Pestaña Plan (`qt_ui/tabs/plan.py`)
- En la cuadrícula de opciones de la tarjeta genérica (`opts_grid`), junto al switch de *Solo audio*:
  - Agregar un toggle / switch: `generic_cookies_toggle`.
  - Etiqueta dinámica: `Cookies (Firefox)` (mostrando el navegador configurado en Opciones).
  - Si no hay navegador configurado (`cookies_from_browser == "None"`):
    - El toggle se deshabilita o permanece oculto con un tooltip explicativo.
  - **Estado inicial inteligente:**
    - Si el enlace es de YouTube (o dominio elegible en el scope): se inicializa en `ON`.
    - Si el enlace es de Pornhub u otro sitio fuera del scope: se inicializa en `OFF`.
    - El usuario tiene la libertad de cambiar el toggle antes de presionar *"Añadir a la cola"*.

### 3.4. Control en el Diálogo de Listas (`qt_ui/dialogs/playlist.py`)
- En la barra de *Opciones de descarga* inferior:
  - Agregar un checkbox: `[✓] Usar cookies del navegador (Firefox)`.
  - Inicializado en `ON` si la lista es de YouTube/TikTok/Instagram y hay navegador configurado; `OFF` en caso contrario.

### 3.5. Creación y Ejecución de Trabajos (`JobOptions`)
- `JobOptions.cookies_browser`:
  - En `main_window.py` (`add_to_queue`):
    - Si el toggle de cookies del video estaba desactivado: `cookies_browser=""`.
    - Si estaba activado: `cookies_browser=self.settings.get("cookies_from_browser", "")`.
- Al ejecutarse el trabajo en `core/download.py` / `core/finalize.py`, solo se incluye `--cookies-from-browser` si `job.opts.cookies_browser` no está vacío.

---

## 4. Plan de Implementación Paso a Paso

- [x] **Paso 1: Módulo Core de Ámbito (`core/cookie_scope.py`)**
  - Implementar lista de dominios conocidos seguros.
  - Implementar `is_cookie_eligible(url, scope_mode)`.
  - Crear tests unitarios en `tests/test_cookie_scope.py`.

- [x] **Paso 2: Ajustes en Ajustes y Opciones (`core/settings.py` & `core/options.py`)**
  - Añadir `cookies_scope` a `DEFAULTS` con valor `"known_only"`.
  - Exponer `cookies_scope` en `JobOptions` / `load_options()`.

- [x] **Paso 3: Actualización de la Pestaña Plan (`qt_ui/tabs/plan.py`)**
  - Añadir control `generic_cookies_toggle` a la tarjeta de detalles.
  - Conectar el estado por defecto al detectar el proveedor/dominio del video.
  - Exponer método `is_cookies_enabled() -> bool`.

- [x] **Paso 4: Actualización del Diálogo de Listas (`qt_ui/playlist_dialog.py`)**
  - Añadir checkbox de cookies a las opciones inferiores de la lista.
  - Exponer método `is_cookies_enabled() -> bool`.

- [x] **Paso 5: Enrutamiento en `main_window.py`**
  - Pasar el estado de cookies al construir el `JobOptions` tanto para videos individuales como para lotes de playlists.

- [x] **Paso 6: Ajustes en la Pestaña de Opciones (`qt_ui/tabs/options.py`)**
  - Añadir fila de control para `cookies_scope` debajo de `cookies_from_browser`.

- [x] **Paso 7: Internacionalización (i18n)**
  - Añadir claves en inglés y español.
  - Ejecutar `python tools/i18n.py check`.

- [x] **Paso 8: Pruebas y Validación**
  - Test de URLs de YouTube (reciben cookies si el toggle está activo).
  - Test de URLs de Pornhub y sitios externos (NO reciben cookies por defecto).
  - Test de conmutación manual del toggle por video.
  - Ejecución de la suite de pruebas (`pytest`).

---

## 5. Criterios de Aceptación

1. **Cero fugas de cookies a sitios externos no deseados:** Al pegar un enlace de Pornhub u otros sitios fuera de la lista segura, yt-dlp nunca ejecuta el argumento `--cookies-from-browser` a menos que el usuario lo active manualmente.
2. **Experiencia fluida en YouTube:** Los videos con restricción de edad de YouTube siguen funcionando sin fricción con el switch activado por defecto.
3. **Transparencia visual:** El usuario siempre ve en la tarjeta del video si se utilizarán cookies y de qué navegador antes de iniciar la descarga.
4. **Todos los tests existentes y nuevos pasan al 100%.**
