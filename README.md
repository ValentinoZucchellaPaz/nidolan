# Mi Drive — nube personal para la LAN

Aplicación monousuario para subir, listar y descargar archivos desde una PC de tu red local. No está diseñada para Internet: no habilites port forwarding en el router ni la expongas fuera de tu LAN.

Para probarla en CachyOS/Arch con tu PC actual, seguí [la guía específica](docs/CACHYOS.md).

## Qué incluye

- Inicio y cierre de sesión con contraseña almacenada como hash `scrypt` en SQLite.
- Subida atómica de archivos: una carga interrumpida no aparece en el listado.
- Listado y descarga autenticados.
- Datos persistentes fuera del contenedor: archivos en `/srv/selfdrive/data` y SQLite en `/srv/selfdrive/state`.

No incluye borrado, carpetas, compartidos, cuotas, sincronización ni múltiples usuarios.

## Instalación en Debian/Ubuntu

1. Instalá Docker Engine y el plugin Docker Compose siguiendo la documentación oficial de Docker. Confirmá la instalación con `docker compose version`.
2. Copiá este proyecto a la PC servidora y ubicá los datos persistentes. Ajustá el UID/GID si tu usuario no es `1000`:

   ```bash
   sudo install -d -o "$USER" -g "$USER" /srv/selfdrive/data /srv/selfdrive/state
   cp .env.example .env
   id -u
   id -g
   openssl rand -hex 32
   ```

3. Editá `.env`: establecé una contraseña larga, pegá la clave generada en `SESSION_SECRET`, completá `PUID` y `PGID`, y reemplazá `BIND_ADDRESS` por la IP que el router reservó para la PC, por ejemplo `192.168.1.50`.
4. Desde el directorio del proyecto, iniciá el servidor:

   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```

5. Desde otro dispositivo conectado a la misma red, abrí `http://IP_RESERVADA:8080`, ingresá con el usuario administrador y probá subir y descargar un archivo.

`restart: unless-stopped` hace que Docker vuelva a levantar el servicio luego de reiniciar la PC. Para administrar el servicio usá `docker compose ps`, `docker compose logs -f` y `docker compose down` (este último no borra los directorios persistentes).

## Reserva DHCP y aislamiento de Internet

En la interfaz del router, buscá **DHCP reservation**, **Address reservation** o una opción similar. Asociá la MAC de la PC a una IP fija y usá esa IP en `BIND_ADDRESS`. La pantalla y nombres concretos cambian según el modelo del router.

No configures redirección de puertos (port forwarding), UPnP ni una DMZ hacia esta PC. Eso mantiene la aplicación fuera de Internet. Como usa HTTP, una futura exposición remota exige HTTPS con proxy inverso, copias de seguridad y control de acceso adicional.

## Copias de seguridad

Detené el servicio antes de una copia consistente y guardá ambos directorios:

```bash
docker compose stop
sudo tar -C /srv/selfdrive -czf selfdrive-backup.tar.gz data state
docker compose start
```

Restaurar una copia requiere detener el servicio y reemplazar **ambos** directorios, porque SQLite y los archivos se corresponden entre sí.

## Desarrollo y pruebas

En un entorno Python con las dependencias de desarrollo instaladas:

```bash
python -m pip install -r requirements-dev.txt
pytest
```
