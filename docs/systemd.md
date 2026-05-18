# SHSE - systemd Service

SHSE ships systemd unit files under `systemd/` so each Docker Compose stack
starts automatically on boot and is manageable with standard `systemctl` commands.

| Unit file | Target VM | Compose file |
|---|---|---|
| `shse.service` | Single-VM (dev/all-in-one) | `docker-compose.yml` |
| `shse-app.service` | App VM (Flask, Celery, Nginx) | `docker-compose.app.yml` |
| `shse-services.service` | Services VM (OpenSearch, MariaDB, Redis, Nutch, Mailpit) | `docker-compose.services.yml` |
| `shse-kiwix.service` | Kiwix VM (offline content) | `docker-compose.kiwix.yml` |

---

## Install (per VM)

Copy the relevant unit file and project files to the VM, then:

```bash
# 1. Deploy the compose file to /opt/shse on the target VM
#    (adjust path in WorkingDirectory inside the .service file if you use a different path)

# 2. Copy the unit file
sudo cp systemd/shse-services.service /etc/systemd/system/shse-services.service
# (replace shse-services with shse-app or shse-kiwix for the other VMs)

# 3. Reload systemd and enable the service
sudo systemctl daemon-reload
sudo systemctl enable shse-services

# 4. Start it now (without waiting for reboot)
sudo systemctl start shse-services
```

Verify it is running (substitute the correct service name):

```bash
systemctl status shse-services
```

Expected output:
```
● shse-services.service - SHSE Services (OpenSearch, MariaDB, Redis, Nutch, Mailpit)
     Loaded: loaded (/etc/systemd/system/shse-services.service; enabled; preset: disabled)
     Active: active (exited) since ...
```

---

## Management

Replace `<unit>` with `shse-app`, `shse-services`, or `shse-kiwix` as appropriate.

| Command | Effect |
|---|---|
| `sudo systemctl start <unit>` | Start the stack |
| `sudo systemctl stop <unit>` | Stop the stack (`docker compose down`) |
| `sudo systemctl restart <unit>` | Stop then start |
| `sudo systemctl reload <unit>` | `docker compose restart` (no down/up cycle) |
| `sudo systemctl status <unit>` | Show current state |
| `sudo systemctl enable <unit>` | Start automatically on boot |
| `sudo systemctl disable <unit>` | Remove autostart |

---

## Logs

View logs from containers on the relevant VM:

```bash
# Service lifecycle events
journalctl -u shse-services   # or shse-app / shse-kiwix

# Follow Docker container logs directly (from the compose file directory)
docker compose -f docker-compose.services.yml logs -f
docker compose -f docker-compose.app.yml logs -f flask
docker compose -f docker-compose.app.yml logs -f celery_worker
```

---

## After updating the code (app VM)

When code or configuration changes on the app VM, rebuild the affected images and reload:

```bash
# Rebuild changed images
docker compose -f docker-compose.app.yml build flask celery_worker celery_beat

# Restart just those containers (no full stack down/up)
docker compose -f docker-compose.app.yml up -d --no-deps flask celery_worker celery_beat

# Or restart the whole stack via systemctl
sudo systemctl restart shse-app
```

---

## Uninstall

```bash
sudo systemctl stop shse-services
sudo systemctl disable shse-services
sudo rm /etc/systemd/system/shse-services.service
sudo systemctl daemon-reload
# Repeat for shse-app and shse-kiwix on their respective VMs
```
