"""Cria (ou troca a senha de) a conta do avaliador e a define como a única que entra.

    python criar_usuario.py email@exemplo.com minha-senha
"""
import sys

from lovable import auth
from lovable.avaliacao import db


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    email, senha = sys.argv[1].strip().lower(), sys.argv[2]
    try:
        auth.criar_ou_trocar_senha(email, senha)
    except ValueError as e:
        print(e)
        return 1
    db.init()
    db.set_setting("dono_email", email)
    print(f"Pronto: {email} é o avaliador. Entre com esse e-mail e a senha informada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
