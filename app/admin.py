from __future__ import annotations

import argparse

from app.main import Settings, reset_admin_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Administración local de Mi Drive")
    parser.add_argument("command", choices=("reset-password",))
    args = parser.parse_args()
    if args.command == "reset-password":
        reset_admin_password(Settings.from_env())
        print("Contraseña del administrador actualizada.")


if __name__ == "__main__":
    main()
