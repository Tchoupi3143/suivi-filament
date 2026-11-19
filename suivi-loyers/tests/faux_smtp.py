# SPDX-License-Identifier: GPL-3.0-or-later
"""Serveur SMTP minimal (sans TLS) pour les tests : garde les messages reçus en mémoire."""
import email
import socketserver
import threading
from email import policy


class FauxSMTP:
    def __init__(self):
        self.messages = []
        parent = self

        class Gestion(socketserver.StreamRequestHandler):
            def handle(self):
                ecrire = lambda l: self.wfile.write(l.encode() + b"\r\n")
                ecrire("220 faux")
                donnees, dans_data, dest = [], False, []
                while True:
                    ligne = self.rfile.readline()
                    if not ligne:
                        return
                    if dans_data:
                        if ligne in (b".\r\n", b".\n"):
                            m = email.message_from_bytes(b"".join(donnees), policy=policy.default)
                            m.destinataires = dest
                            parent.messages.append(m)
                            donnees, dans_data, dest = [], False, []
                            ecrire("250 ok")
                        else:
                            donnees.append(ligne[1:] if ligne.startswith(b"..") else ligne)
                        continue
                    cmd = ligne.decode(errors="replace").strip().upper()
                    if cmd.startswith("EHLO"):
                        ecrire("250-faux"); ecrire("250 AUTH PLAIN LOGIN")
                    elif cmd.startswith("AUTH"):
                        ecrire("235 ok")
                    elif cmd.startswith("RCPT TO:"):
                        dest.append(ligne.decode().strip()[8:].strip("<> "))
                        ecrire("250 ok")
                    elif cmd == "DATA":
                        dans_data = True
                        ecrire("354 go")
                    elif cmd == "QUIT":
                        ecrire("221 bye")
                        return
                    else:
                        ecrire("250 ok")

        self.serveur = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Gestion)
        self.serveur.daemon_threads = True
        self.port = self.serveur.server_address[1]
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def arreter(self):
        self.serveur.shutdown()
        self.serveur.server_close()
