"""Point d'entrée de l'interface graphique GTK 3.

Lancé via ``python3 -m qcm_papier``. Si GTK n'est pas disponible, on bascule
sur la CLI.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    # Si des arguments de sous-commande sont passés, on utilise la CLI.
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] in ("generate", "correct", "check", "-h", "--help"):
        from .cli import main as cli_main
        return cli_main(argv)

    # Sinon, on lance l'interface graphique.
    try:
        from .ui.app import run
    except ImportError as e:
        print(f"Interface graphique indisponible ({e}).", file=sys.stderr)
        print("Utilisez la ligne de commande : qcm-papier <generate|correct|check>",
              file=sys.stderr)
        return 1
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
