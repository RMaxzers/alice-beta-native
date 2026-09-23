# Guía DHCP del Laboratorio Demo

> Dataset sintético de demostración. Red y equipos ficticios.

## Resumen

El Laboratorio Demo usa un único servidor DHCP (`dhcp-demo-01`, 192.168.10.2) para la red de oficina 192.168.10.0/24.
El arrendamiento por defecto dura 8 horas.

## Reserva de direcciones

El rango 192.168.10.1–192.168.10.49 está reservado para infraestructura (router, servidores e impresoras) y
nunca se entrega por DHCP. El pool dinámico va de 192.168.10.50 a 192.168.10.200.

## Procedimiento ante conflicto de IP

1. Identificar la MAC en la tabla de arrendamientos del servidor.
2. Comprobar si la IP pertenece al rango reservado; si es así, retirar la configuración estática errónea del equipo.
3. Liberar y renovar el arrendamiento en el cliente.

## Contacto

Equipo de redes del Laboratorio Demo (buzón ficticio: redes@laboratorio-demo.invalid).
