# Probar Mi Drive en CachyOS

La aplicación no cambia para CachyOS: Docker ejecuta el mismo contenedor Linux que en Debian/Ubuntu. Esta rama cambia únicamente la preparación del host y agrega una configuración local de prueba.

## 1. Verificar Docker

En CachyOS/Arch, Docker y Compose se instalan desde los repositorios oficiales:

```bash
sudo pacman -Syu docker docker-compose
sudo systemctl enable --now docker.service
sudo usermod -aG docker "$USER"
```

Cerrá sesión y volvé a entrar para que el grupo `docker` se aplique. Luego comprobá:

```bash
docker compose version
docker ps
```

Si ya tenés `docker` y `docker-compose` instalados, ejecutá solo los comandos de `systemctl` y `usermod` que todavía necesites.

## 2. Iniciar una prueba local

Desde la raíz del proyecto:

```bash
cp .env.cachyos.example .env
openssl rand -hex 32
```

Editá `.env`: cambiá `ADMIN_PASSWORD` y pegá la clave generada en `SESSION_SECRET`. Para tu usuario actual, `PUID=1000` y `PGID=1000` son correctos; verificá ambos con `id -u` e `id -g` si usás otra cuenta.

Después iniciá la aplicación:

```bash
docker compose up -d --build
docker compose logs -f
```

Abrí [http://127.0.0.1:8080](http://127.0.0.1:8080) en esa misma PC. Podés detenerla con `docker compose down`; los datos de la prueba quedan en `.selfdrive/`, fuera de Git.

## 3. Probarla desde otro equipo de la LAN

Cuando la prueba local funcione, cambiá `BIND_ADDRESS` por la IP Wi-Fi/Ethernet de esta PC, por ejemplo `192.168.1.50`. Consultala con `hostname -I` y mantenela estable mediante una reserva DHCP en el router. Después reiniciá el servicio:

```bash
docker compose up -d
```

Abrí `http://IP_DE_ESTA_PC:8080` desde otro equipo o celular conectado a la misma red. No configures port forwarding, UPnP ni DMZ en el router: el servidor seguirá accesible solo dentro de la LAN.
