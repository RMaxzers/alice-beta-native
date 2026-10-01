from __future__ import annotations

import argparse
import getpass
import json
import sys
import uuid

import httpx

from alice_cli.storage import Storage


class ClientError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


class Client:
    def __init__(self, storage, profile, transport=None):
        self.storage, self.profile = storage, profile
        self.url = storage.url(profile)
        self.session = storage.session(profile, self.url)
        # Never forward cookies/passwords through redirects; TLS verification stays on.
        self.http = httpx.Client(base_url=self.url, timeout=httpx.Timeout(120, connect=10),
                                 follow_redirects=False, verify=True, trust_env=False, transport=transport)
        if self.session.get("cookie"):
            self.http.cookies.set("alice_session", self.session["cookie"])

    def check(self, response):
        if response.status_code == 401:
            self.storage.clear(self.profile)
            raise ClientError("Sesión ausente o expirada. Ejecuta alice login con este perfil.", 3)
        if response.status_code >= 300:
            try:
                detail = response.json().get("detail", "Petición rechazada")
            except ValueError:
                detail = "Respuesta inválida del servidor"
            raise ClientError(f"HTTP {response.status_code}: {detail}", 4)
        return response

    def request(self, method, path, **kwargs):
        headers = {"x-csrf-token": self.session.get("csrf", "")}
        return self.check(self.http.request(method, path, headers=headers, **kwargs)).json()

    def login(self, username, password):
        r = self.check(self.http.post("/api/login", json={"username": username, "password": password}))
        data = r.json()
        cookie = self.http.cookies.get("alice_session")
        if not cookie:
            raise ClientError("El servidor no devolvió una cookie de sesión")
        self.session = {**data, "cookie": cookie, "url": self.url}
        self.storage.save(self.profile, self.session)

    def chat(self, message, cid=None, privacy="PRIVATE", ticket=None):
        payload = {"message": message, "privacy": privacy, "client_request_id": uuid.uuid4().hex}
        if cid:
            payload["conversation_id"] = cid
        if ticket:
            payload["authorization_ticket"] = ticket
        preview, failed, done = None, False, False
        with self.http.stream("POST", "/api/chat", json=payload, headers={"x-csrf-token": self.session.get("csrf", "")}) as r:
            if r.status_code >= 300:
                r.read()
                self.check(r)
            for line in r.iter_lines():
                if not line:
                    continue
                ev = json.loads(line)
                kind = ev.get("type")
                if kind == "conversation":
                    cid = ev["conversation_id"]
                    print(f"Conversación: {cid}", file=sys.stderr)
                elif kind == "token":
                    print(ev["text"], end="", flush=True)
                elif kind == "action":
                    print(ev.get("message", ""), flush=True)
                elif kind == "authorization_required":
                    preview = ev["preview"]
                    print("\nRequiere autorización de salida:", json.dumps(preview, ensure_ascii=False))
                elif kind == "error":
                    failed = True
                    print(ev.get("message", "Error en la generación"), file=sys.stderr)
                elif kind == "done":
                    done = True
                    failed |= ev.get("status", "complete") in ("failed", "interrupted")
        print()
        if not done and not (failed or preview):
            raise ClientError(f"Conexión interrumpida; consulta la conversación {cid}. Una acción podría haberse ejecutado.", 5)
        return cid, preview, failed


def parser():
    p = argparse.ArgumentParser(prog="alice", description="Cliente de Alice: mismo usuario, conversaciones y tareas que la web")
    p.add_argument("--profile", default="local")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("login", "logout", "status"):
        s = sub.add_parser(name)
        s.add_argument("--profile", default=argparse.SUPPRESS)
    c = sub.add_parser("chat")
    c.add_argument("--profile", default=argparse.SUPPRESS)
    c.add_argument("--conversation", help="Reanudar una conversación persistida")
    c.add_argument("--list", action="store_true", help="Listar conversaciones")
    c.add_argument("--privacy", choices=("PUBLIC", "INTERNAL", "PRIVATE"), default="PRIVATE")
    c.add_argument("--message", help="Un solo turno (por defecto: chat interactivo)")
    t = sub.add_parser("tasks")
    t.add_argument("--profile", default=argparse.SUPPRESS)
    ts = t.add_subparsers(dest="task_command", required=True)
    tl = ts.add_parser("list")
    tl.add_argument("--profile", default=argparse.SUPPRESS)
    pr = sub.add_parser("profile").add_subparsers(dest="profile_command", required=True)
    ps = pr.add_parser("set")
    ps.add_argument("name")
    ps.add_argument("--url", required=True)
    return p


def run(args, storage):
    if args.command == "profile":
        storage.set_url(args.name, args.url)
        print(f"Perfil {args.name} configurado. Inicia sesión para ese endpoint.")
        return 0
    c = Client(storage, args.profile)
    try:
        if args.command == "login":
            print(f"Endpoint: {c.url}")
            c.login(input("Usuario: ").strip(), getpass.getpass("Contraseña: "))
            print("Sesión iniciada.")
        elif args.command == "logout":
            c.request("POST", "/api/logout")
            storage.clear(args.profile)
            print("Sesión revocada.")
        elif args.command == "status":
            session = c.request("GET", "/api/session")
            identity = c.request("GET", "/api/identity")
            print(json.dumps({"endpoint": c.url, "user": session["user"], "expires_at": session["expires_at"], **identity}, ensure_ascii=False, indent=2))
        elif args.command == "tasks":
            print(json.dumps(c.request("GET", "/api/tasks"), ensure_ascii=False, indent=2))
        elif args.list:
            print(json.dumps(c.request("GET", "/api/conversations"), ensure_ascii=False, indent=2))
        else:
            cid = args.conversation
            if cid:
                prior = c.request("GET", f"/api/conversations/{cid}")
                for m in prior["messages"]:
                    print(f"{m['role']}: {m['content']}")
            while True:
                message = args.message if args.message is not None else input("Tú (/salir): ")
                if message == "/salir":
                    break
                if not message.strip():
                    continue
                cid, preview, failed = c.chat(message, cid, args.privacy)
                if preview and args.message is None:
                    if input("Escribe AUTORIZAR para enviar ese payload una vez; Enter para cancelar: ") == "AUTORIZAR":
                        tid = preview["ticket_request_id"]
                        c.request("POST", f"/api/egress/{tid}/approve")
                        cid, preview, failed = c.chat(message, cid, args.privacy, tid)
                if args.message is not None:
                    return 4 if failed or preview else 0
    finally:
        c.http.close()
    return 0


def main(argv=None):
    try:
        return run(parser().parse_args(argv), Storage())
    except KeyboardInterrupt:
        print("\nCliente desconectado. No se deshacen acciones; consulta la conversación antes de reintentar.", file=sys.stderr)
        return 130
    except EOFError:
        return 0
    except ClientError as e:
        print(str(e), file=sys.stderr)
        return e.code
    except httpx.HTTPError:
        print("No se pudo conectar de forma segura a Alice. Comprueba endpoint, red y certificado TLS.", file=sys.stderr)
        return 5
    except (ValueError, OSError):
        print("Configuración, sesión o respuesta inválida; comprueba el perfil y vuelve a iniciar sesión.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
