"""Mutual-TLS operator endpoint for Phase 7 prompt-change requests."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import ssl


def certificate_common_name(certificate):
    """Return a single peer CN; ambiguous or absent identities fail closed."""
    if not isinstance(certificate, dict):
        return None
    names = [value for rdn in certificate.get("subject", ())
             for key, value in rdn if key == "commonName"]
    return names[0] if len(names) == 1 and isinstance(names[0], str) else None


def create_operator_server(*, controller, host, port, server_cert, server_key,
                           client_ca, authorized_operators, max_body_bytes=1024):
    """Create a TLS server requiring client certs mapped to operator credentials.

    The embedding deployment must restrict network access to this listener and
    provide its server/client CA material through managed secrets.
    """
    operators = dict(authorized_operators)
    if not operators or any(not isinstance(cn, str) or not cn or
                            not isinstance(credential, str) or not credential
                            for cn, credential in operators.items()):
        raise ValueError("explicit certificate-CN to operator credential map required")
    if type(max_body_bytes) is not int or not 1 <= max_body_bytes <= 4096:
        raise ValueError("operator request body bound must be 1..4096 bytes")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def reply(self, status, payload):
            data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/v1/prompt-transitions":
                self.reply(404, {"error": "not_found"})
                return
            cn = certificate_common_name(self.connection.getpeercert())
            credential = operators.get(cn)
            if credential is None:
                self.reply(403, {"error": "operator_certificate_not_authorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 <= length <= max_body_bytes:
                    raise ValueError("request body size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or set(body) != {"prompt"}:
                    raise ValueError("request schema")
                result = controller.transition({"action": "change_prompt",
                    "token": credential, "prompt": body["prompt"],
                    "operator_id": cn})
                self.reply(200, {"result": result})
            except (ValueError, json.JSONDecodeError) as error:
                self.reply(400, {"error": str(error)})
            except PermissionError as error:
                self.reply(403, {"error": str(error)})
            except TimeoutError as error:
                self.reply(504, {"error": str(error)})
            except Exception as error:
                # Keep credentials and request contents out of logs while
                # making fixture and deployment failures diagnosable.
                print(f"Phase 7 transition failed: {type(error).__name__}",
                      flush=True)
                self.reply(409, {"error": "transition_failed"})

    class ReusableHTTPServer(HTTPServer):
        allow_reuse_address = True

    server = ReusableHTTPServer((host, port), Handler)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile=server_cert, keyfile=server_key)
    context.load_verify_locations(cafile=client_ca)
    context.verify_mode = ssl.CERT_REQUIRED
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server
