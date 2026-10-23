# NidoLAN

**Tus archivos, en tu casa.** NidoLAN es una pequeña nube personal para usar desde cualquier navegador de tu red local. Corre en una PC con Docker: podés guardar archivos en Mi Drive y navegar carpetas que ya existen en el equipo sin copiarlas.

Es un proyecto monousuario y en desarrollo. Sirve para aprender y experimentar con redes, almacenamiento y una aplicación web self hosted; no está preparado para exponerse directamente a Internet.

## Qué podés hacer

- Entrar con contraseña desde una PC o un celular de la misma LAN.
- Crear carpetas, subir, renombrar, mover y descargar archivos en **Mi Drive**.
- Vincular otras carpetas del host en **solo lectura**, por ejemplo apuntes o películas. Sus archivos permanecen en la ruta original.
- Buscar dentro de la carpeta abierta y ordenar por nombre o fecha.

**Todavía no incluye** vista previa, borrado, sincronización automática, compartidos ni varios usuarios. La [especificación y hoja de ruta](docs/SPEC.md) detalla lo implementado y lo próximo.

## Probarlo en CachyOS / Arch

Necesitás Docker y Docker Compose. Con Docker funcionando, desde la raíz del repositorio:

```bash
cp .env.cachyos.example .env
install -d -m 700 .selfdrive/data .selfdrive/state
openssl rand -hex 32
```

Editá `.env`: elegí `ADMIN_USERNAME` y una contraseña larga en `ADMIN_PASSWORD`, pegá la clave generada en `SESSION_SECRET` y cambiá `LIBRARY_PATH` por una carpeta **existente** de tu PC. Esa carpeta se mostrará como «Facultad» inicialmente; podés darle otro nombre o sumar más ubicaciones después.

```bash
docker compose up -d --build
docker compose ps
```

Abrí [http://127.0.0.1:8080](http://127.0.0.1:8080). Para entrar desde el celular, conectalo a la misma Wi-Fi, cambiá `BIND_ADDRESS` en `.env` por la IP local de la PC y ejecutá `docker compose up -d`. Consultá la IP con `hostname -I`; una reserva DHCP en el router evita que cambie. La [guía de CachyOS](docs/CACHYOS.md) incluye la instalación de Docker y más detalles.

## Instalarlo en Debian / Ubuntu

Instalá Docker Engine y el plugin Compose. Creá los directorios persistentes y copiá la configuración:

```bash
sudo install -d -o "$USER" -g "$USER" /srv/selfdrive/data /srv/selfdrive/state /srv/selfdrive/library
cp .env.example .env
id -u
id -g
openssl rand -hex 32
```

En `.env`, completá usuario, contraseña y clave de sesión, ajustá `PUID`/`PGID` según los valores de `id`, y poné en `BIND_ADDRESS` la IP local reservada para el servidor. Luego iniciá con `docker compose up -d --build` y abrí `http://IP_DEL_SERVIDOR:8080` desde la LAN.

## Vincular más carpetas sin duplicarlas

Cada ubicación necesita un nombre y dos rutas: una carpeta real del host y su punto de montaje dentro del contenedor.

1. Copiá `sources.example.json` a `sources.json` y cambiá `SOURCES_CONFIG=./sources.json` en `.env`.
2. Agregá una entrada con identificador, nombre y ruta interna:

   ```json
   [
     {"id": "facultad", "name": "Facultad", "path": "/library"},
     {"id": "peliculas", "name": "Películas", "path": "/libraries/peliculas"}
   ]
   ```

3. Copiá `compose.sources.example.yaml` a `compose.override.yaml`. Cambiá la ruta de ejemplo por tu carpeta real y agregá un montaje `:ro` por cada ubicación nueva.
4. Aplicá los cambios con `docker compose up -d --force-recreate`.

`sources.json` y `compose.override.yaml` son locales y están ignorados por Git. Si se desconecta una carpeta, NidoLAN la marca como no disponible y el resto sigue funcionando.

## Datos y seguridad

Mi Drive guarda los archivos con nombres internos aleatorios en `DATA_DIR` y sus metadatos y el hash de la contraseña en SQLite, dentro de `STATE_DIR`. Ambos directorios están fuera del contenedor. Una carpeta vinculada se monta en solo lectura y no se copia a `DATA_DIR`.

`.env`, la base de datos, los archivos subidos y las rutas personales de `sources.json` y `compose.override.yaml` **no se suben a Git**. No abras el puerto 8080 a Internet mediante port forwarding, UPnP o DMZ: el login de esta versión usa HTTP para la LAN. Para acceso remoto hacen falta HTTPS, copias de seguridad y una arquitectura de acceso segura.

Para respaldar Mi Drive, detené el servicio (`docker compose stop`), copiá **juntos** `DATA_DIR` y `STATE_DIR`, y volvé a iniciarlo (`docker compose start`). Para cambiar la contraseña, editá `.env`, ejecutá `docker compose up -d --force-recreate` y luego `docker compose exec selfdrive python -m app.admin reset-password`.

## Desarrollo

Backend en Python/FastAPI, páginas HTML con CSS y JavaScript pequeños, SQLite y un contenedor Docker. `app/main.py` ensambla routers; la autenticación, el explorador, la base y las ubicaciones vinculadas están en módulos separados.

```bash
python -m pip install -r requirements-dev.txt
pytest
```

Las ramas se usan así: `main` es la versión recomendada, `cachyos` es la rama de trabajo para nuevas funciones y `debian` conserva la versión anterior orientada a Debian/Ubuntu.

## Licencia

MIT. Ver [LICENSE](LICENSE).
