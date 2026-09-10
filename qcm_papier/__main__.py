"""Point d'entrée de l'interface graphique GTK 4.

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

    # Sans argument : on tente l'interface graphique. Si GTK n'est pas
    # disponible, on bascule sur la CLI qui génère le sujet du projet par
    # défaut (math/2026/OML1_bis.json -> math/2026/OML1_bis.pdf).
    try:
        from .ui.app import run
    except ImportError:
        from .cli import main as cli_main
        return cli_main(argv)
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
