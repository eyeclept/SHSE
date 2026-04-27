# SHSE - systemd Service

SHSE ships a systemd unit file at `systemd/shse.service` so the full Docker
Compose stack starts automatically on boot and is manageable with standard
`systemctl` commands.

---

## Install

```bash
# Copy the unit file
sudo cp systemd/shse.service /etc/systemd/system/shse.service

# Reload systemd and enable the service
sudo systemctl daemon-reload
sudo systemctl enable shse

# Start it now (without waiting for reboot)
sudo systemctl start shse
```

Verify it is running:

```bash
systemctl status shse
```

Expected output:
```
● shse.service - SHSE - Self-Hosted Search Engine
     Loaded: loaded (/etc/systemd/system/shse.service; enabled; preset: disabled)
     Active: active (exited) since ...
```

---

## Management

| Command | Effect |
|---|---|
| `sudo systemctl start shse` | Start the stack |
| `sudo systemctl stop shse` | Stop the stack (`docker compose down`) |
| `sudo systemctl restart shse` | Stop then start |
| `sudo systemctl reload shse` | `docker compose restart` (no down/up cycle) |
| `sudo systemctl status shse` | Show current state |
| `sudo systemctl enable shse` | Start automatically on boot |
| `sudo systemctl disable shse` | Remove autostart |

---

## Logs

View logs from all SHSE containers via journald:

```bash
# Service lifecycle events
journalctl -u shse

# Follow Docker container logs directly
docker compose logs -f
docker compose logs -f flask
docker compose logs -f celery_worker
```

---

## After updating the code

When code or configuration changes, rebuild the affected images and reload:

```bash
# Rebuild changed images
docker compose build flask celery_worker celery_beat

# Restart just those containers (no full stack down/up)
docker compose up -d --no-deps flask celery_worker celery_beat

# Or restart the whole stack via systemctl
sudo systemctl restart shse
```

---

## Uninstall

```bash
sudo systemctl stop shse
sudo systemctl disable shse
sudo rm /etc/systemd/system/shse.service
sudo systemctl daemon-reload
```
