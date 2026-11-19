"""Genera un token de dispositivo aleatorio para API_TOKENS.

Uso: python scripts/new_token.py
Añade el valor a API_TOKENS (separados por comas) en el servidor y pégalo en la
app iOS (Configuración → Servidor → Token). Se guarda en el Llavero del iPhone.
"""

import secrets

print(secrets.token_urlsafe(32))
