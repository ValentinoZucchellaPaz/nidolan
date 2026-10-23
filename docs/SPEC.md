# Mi Drive — especificación del explorador

## Objetivo y alcance

Una persona administra archivos desde una PC servidora en la LAN y los abre desde navegador de escritorio o celular. Hay dos espacios: **Mi Drive**, gestionado por la app, y **ubicaciones vinculadas**, carpetas del host montadas en modo solo lectura. La primera entrega permite navegar, buscar dentro de la carpeta visible, ordenar, subir, descargar, crear carpetas, renombrar y mover elementos gestionados. No incluye borrar, compartir ni acceso desde Internet.

## Recorridos y navegación

1. Después de entrar, Inicio muestra ubicaciones y archivos recientes. La barra lateral permite ir a Mi Drive o a cualquier ubicación vinculada.
2. En una carpeta, las migas de pan y Volver permiten regresar; cada carpeta se abre desde toda su fila. En celular la barra lateral se abre desde el encabezado.
3. En Mi Drive, Subir usa la carpeta actual como destino. + Carpeta crea una subcarpeta. El menú `···` de una fila permite renombrar o mover; el destino se elige de las carpetas gestionadas o de la raíz.
4. Un archivo se descarga desde toda la fila. La búsqueda filtra solo los elementos visibles de esa carpeta. El orden se elige entre nombre y fecha reciente.
5. Una ubicación sin montar sigue visible e informa cómo recuperarla. No bloquea Mi Drive ni otras ubicaciones.

## Contrato HTTP y datos

Todas las rutas siguientes requieren sesión, salvo login y los assets estáticos:

| Método y ruta | Comportamiento |
| --- | --- |
| `GET /` | Inicio y archivos recientes |
| `GET /drive`, `GET /drive/{folder_id}` | Explorar raíz o carpeta gestionada; `?sort=name|date` |
| `POST /folders` | Crear con campos `parent` y `name` |
| `POST /files` | Subir `upload` a `parent` |
| `POST /nodes/{id}/rename` | Renombrar con `name` |
| `POST /nodes/{id}/move` | Mover con `destination` (vacío = raíz) |
| `GET /files/{id}/download` | Descargar archivo gestionado |
| `GET /sources/{id}/{path}` | Explorar carpeta vinculada |
| `GET /source-download/{id}/{path}` | Descargar archivo vinculado |

`/facultad` y `/facultad-descarga/...` redirigen a las rutas nuevas por compatibilidad. Los nodos gestionados residen en SQLite; los archivos físicos mantienen su nombre interno no predecible en `/data`. La migración `user_version=1` copia los registros de `files` a `nodes` sin mover blobs ni cambiar IDs. La tabla anterior se conserva para facilitar inspección o recuperación, pero `nodes` pasa a ser la fuente activa.

Una configuración JSON registra `id`, nombre visible y ruta **interna** de cada ubicación. Docker monta la ruta del host en esa ruta interna con `:ro`. Los cambios de configuración requieren reinicio del contenedor. El servidor resuelve y valida cada ruta bajo la raíz correspondiente; un enlace simbólico que sale de ella no se lista ni se descarga.

Los nombres vacíos, `.`/`..`, separadores y NUL son inválidos. Crear, mover o renombrar hacia un nombre existente entre hermanos devuelve conflicto 409. Mover una carpeta a sí misma o bajo una descendiente devuelve 400. Una carpeta inexistente devuelve 404; una fuente sin montar se presenta como desconectada.

## Estados y criterios de aceptación

- Login correcto/incorrecto y logout; todas las operaciones de contenido bloqueadas sin sesión.
- Un archivo previo a la migración sigue en la raíz de Mi Drive, se descarga con el mismo contenido y la migración no duplica registros tras reiniciar.
- Carpetas anidadas, renombre y movimiento funcionan; ciclos y conflictos se rechazan sin alterar datos.
- Fuentes múltiples se navegan sin copiar archivos. Una fuente desconectada no rompe las demás; rutas `..` y symlinks externos no exponen archivos.
- Escritorio y celular permiten llegar a cada ubicación, volver por la ruta, abrir carpetas y descargar pulsando toda la fila. El foco de teclado es visible y los controles tienen nombre accesible.
- Subidas muestran progreso o un error comprensible. Los datos gestionados sobreviven al reinicio del contenedor.

## Próximas funciones, por prioridad

1. **Vista previa:** primero PDF e imágenes mediante respuesta autenticada en línea con MIME seguro; validar vídeos grandes y solicitudes Range antes de incorporarlos. Archivos activos o desconocidos seguirán descargándose.
2. **Búsqueda global:** consulta entre Mi Drive y fuentes vinculadas, con estados para fuentes desconectadas.
3. **Cuadrícula:** alternativa a la lista para colecciones visuales.
4. **Papelera:** borrado recuperable y política de retención, después de definir copias de seguridad.
5. **Compartidos:** necesitará definir usuarios, permisos y exposición segura antes de implementarse.
