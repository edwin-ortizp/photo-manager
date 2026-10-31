"""Direcciones de interfaces locales, sin consultar servicios externos."""
import ipaddress
import json
import os
import socket
import subprocess


def direcciones():
    candidatos = []
    if os.name == "nt":
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                "@(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.AddressState -eq 'Preferred' } | Select-Object -ExpandProperty IPAddress) | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
            datos = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
            candidatos.extend([datos] if isinstance(datos, str) else datos)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if not candidatos:
        try:
            candidatos.extend(x[4][0] for x in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
        except OSError:
            pass
    salida = set()
    for valor in candidatos:
        try:
            ip = ipaddress.ip_address(valor)
            if ip.version == 4 and not (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast):
                salida.add(str(ip))
        except ValueError:
            pass
    return sorted(salida)


def conexion(host, puerto):
    habilitada = host not in ("127.0.0.1", "localhost", "::1")
    ips = direcciones() if host in ("0.0.0.0", "::") else ([host] if habilitada else [])
    return {"habilitada": habilitada, "puerto": puerto,
            "urls": [f"http://{ip}:{puerto}" for ip in ips]}
