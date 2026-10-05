#!/usr/bin/env bash
# Install using Docker's signed Ubuntu apt repository; run from Termius with sudo.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
  printf '%s\n' 'Ejecuta: sudo bash install-docker.sh'
  exit 1
fi
owner="${1:-${SUDO_USER:-}}"
if [[ -z "$owner" || "$owner" == root ]] || ! id "$owner" >/dev/null 2>&1; then
  printf '%s\n' 'Indica el usuario de Ubuntu: sudo bash install-docker.sh eva2'
  exit 1
fi
. /etc/os-release
[[ "$ID" == ubuntu ]] || { printf '%s\n' 'Este instalador requiere Ubuntu.'; exit 1; }
for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
  if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
    printf 'Ya existe %s; revisa la instalación actual antes de migrarla.\n' "$package"
    exit 1
  fi
done
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
# Docker membership gives host administration rights; no passwordless sudo rule is created.
usermod -aG docker "$owner"
docker version --format '{{.Server.Version}}'
docker compose version
printf '\nDocker listo. Las nuevas conexiones SSH de %s tendrán acceso a Docker.\n' "$owner"
