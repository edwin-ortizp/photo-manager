"""CLI del gestor de fotos.

    python fotos.py organizar [--aplicar]
    python fotos.py deshacer datos/movimientos-XXXX.csv
"""
import argparse
from collections import Counter
from pathlib import Path


def cmd_organizar(args):
    from pm.organizar import organizar
    plan = organizar(simular=not args.aplicar)
    por_fuente = Counter(p["fuente_fecha"] for p in plan)
    por_carpeta = Counter(Path(p["destino"]).parent.name for p in plan)
    print(f"{len(plan)} archivos {'movidos' if args.aplicar else 'por mover (simulacion)'}")
    print("Fecha tomada de:", dict(por_fuente))
    for carpeta, n in sorted(por_carpeta.items()):
        print(f"  {carpeta}: {n}")
    for p in plan[:: max(1, len(plan) // 12)][:12]:
        print(f"  {Path(p['origen']).name}  ->  {Path(p['destino']).parent.name}/{Path(p['destino']).name}")


def cmd_deshacer(args):
    from pm.organizar import deshacer
    deshacer(Path(args.bitacora))
    print("Movimientos revertidos.")


def cmd_indexar(args):
    from pm import indice
    from pm.exif import ExifTool
    db = indice.conectar()
    with ExifTool() as et:
        n = indice.sincronizar(db, et)
    print(f"{n} cambios en el indice")
    if args.miniaturas:
        from concurrent.futures import ThreadPoolExecutor
        rutas = [r["ruta"] for r in db.execute("SELECT ruta FROM fotos")]
        with ThreadPoolExecutor() as pool:
            for i, _ in enumerate(pool.map(indice.miniatura, rutas), 1):
                if i % 250 == 0 or i == len(rutas):
                    print(f"Miniaturas {i}/{len(rutas)}")


def cmd_clasificar(args):
    from pm import ia, indice
    from pm.exif import ExifTool
    db = indice.conectar()
    with ExifTool() as et:
        indice.sincronizar(db, et, progreso=lambda *_: None)
        fotos = ia.pendientes(db, args.limite, args.carpeta)
        print(f"{len(fotos)} fotos por clasificar en lotes de {args.lote}")
        total = {"ok": 0, "error": 0, "movidas": 0}
        for n, i in enumerate(range(0, len(fotos), args.lote), 1):
            lote = ia.preparar_lote(fotos[i:i + args.lote], n)
            try:
                resultados = ia.invocar_claude(lote)
            except Exception as e:
                print(f"  lote {n}: ERROR {e}")
                continue
            r = ia.aplicar(db, et, resultados)
            for k in total:
                total[k] += r[k]
            print(f"  lote {n}: {r}")
    print("Total:", total)


def cmd_panel(args):
    import socket
    import uvicorn
    url = f"http://127.0.0.1:{args.puerto}"
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", args.puerto)) == 0:
            print(f"El puerto {args.puerto} ya esta en uso. Si es el panel, abre {url}; "
                  f"si no, usa otro: python fotos.py panel --puerto {args.puerto + 1}")
            return
    print(f"Panel en {url}")
    from pm.panel import app
    app.state.host = args.host
    app.state.puerto = args.puerto
    if args.sin_navegador:
        uvicorn.run(app, host=args.host, port=args.puerto, log_level="warning")
    else:
        from pm.escritorio import abrir_panel
        try:
            abrir_panel(app, args.host, args.puerto, navegador=args.navegador)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc


def main():
    ap = argparse.ArgumentParser(prog="fotos")
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("organizar", help="Mueve fotos a <anio>/ con nombre por fecha")
    p.add_argument("--aplicar", action="store_true", help="Sin esto solo simula")
    p.set_defaults(fn=cmd_organizar)
    p = sub.add_parser("deshacer", help="Revierte una reorganizacion usando su bitacora")
    p.add_argument("bitacora")
    p.set_defaults(fn=cmd_deshacer)
    p = sub.add_parser("indexar", help="Actualiza el indice (y opcionalmente las miniaturas)")
    p.add_argument("--miniaturas", action="store_true")
    p.set_defaults(fn=cmd_indexar)
    p = sub.add_parser("clasificar", help="Clasifica con Claude Haiku las fotos sin _ia|*")
    p.add_argument("--limite", type=int, default=20, help="Maximo de fotos en esta corrida")
    p.add_argument("--lote", type=int, default=10, help="Fotos por llamada a Claude")
    p.add_argument("--carpeta", default="", help="Solo esta carpeta (ej: 2025, sin-fecha)")
    p.set_defaults(fn=cmd_clasificar)
    p = sub.add_parser("panel", help="Abre el panel web local")
    p.add_argument("--puerto", "--port", type=int, default=8642)
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 permite acceso desde el celular; 127.0.0.1 restringe al PC")
    modo = p.add_mutually_exclusive_group()
    modo.add_argument("--sin-navegador", action="store_true", help="Inicia solo el servidor")
    modo.add_argument("--navegador", action="store_true", help="Abre una pestaña en vez de la ventana de escritorio")
    p.set_defaults(fn=cmd_panel)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()

