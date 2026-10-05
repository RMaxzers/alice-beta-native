#!/usr/bin/env bash
# Configure only the second VirtualBox adapter; keep the existing SSH/NAT adapter.
set -euo pipefail
vm_user="${1:-eva2}"
lan_interface="${2:-enp0s8}"
[[ $EUID -eq 0 ]] || { echo 'Ejecuta este paso con sudo, en Ubuntu.' >&2; exit 1; }
[[ "$vm_user" =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 1
[[ "$lan_interface" =~ ^enp[0-9]+s[0-9]+$ && "$lan_interface" != enp0s3 ]] || exit 1
user_home="$(getent passwd "$vm_user" | cut -d: -f6)"
[[ -d "$user_home/alice-home" ]] || { echo 'No encuentro alice-home.' >&2; exit 1; }
[[ -f "/sys/class/net/$lan_interface/address" ]] || { echo 'Falta el segundo adaptador puente de VirtualBox.' >&2; exit 1; }
lan_mac="$(cat "/sys/class/net/$lan_interface/address")"
[[ "$lan_mac" =~ ^([a-f0-9]{2}:){5}[a-f0-9]{2}$ ]] || exit 1
netplan_file=/etc/netplan/90-alice-home-lan.yaml
if [[ -e "$netplan_file" ]] && ! grep -q '^# Alice home LAN adapter$' "$netplan_file"; then
  echo 'Ya existe un archivo de red ajeno a este perfil; se conserva.' >&2; exit 1
fi
umask 077
if [[ -f "$netplan_file" ]]; then cp -- "$netplan_file" "$netplan_file.before"; fi
cat > "$netplan_file" <<YAML
# Alice home LAN adapter
network:
  version: 2
  ethernets:
    alice_lan:
      match:
        macaddress: "$lan_mac"
      dhcp4: true
      dhcp6: false
      accept-ra: false
      optional: true
      dhcp4-overrides:
        route-metric: 200
        use-dns: false
YAML
chmod 600 "$netplan_file"
netplan generate
netplan apply
lan_ip=''
for _ in {1..15}; do
  lan_ip="$(ip -4 -o addr show dev "$lan_interface" scope global | awk 'NR==1 {split($4,a,"/"); print a[1]}')"
  [[ -n "$lan_ip" ]] && break
  sleep 2
done
[[ -n "$lan_ip" ]] || { echo 'El router todavía no entregó una IP. Revisa el adaptador puente y vuelve a ejecutar.' >&2; exit 1; }
runuser -u "$vm_user" -- bash "$user_home/alice-home/scripts/linux/start-home-lan.sh" "$lan_ip"
printf 'Reserva esta IP en el router para la MAC %s: %s\n' "$lan_mac" "$lan_ip"
