"""Interface en ligne de commande pour qcm-papier.

Permet de :
* générer le sujet PDF à partir d'un projet JSON (``qcm-papier generate``) ;
* corriger un lot de copies scannées et exporter les notes Scodoc
  (``qcm-papier correct``) ;
* valider qu'un projet est bien formé (``qcm-papier check``).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import generator, pdf_writer, project as project_mod, scanner, scodoc


def _load_project(path: str):
    """Charge un projet depuis un fichier JSON."""
    if not os.path.exists(path):
        raise SystemExit(f"Projet introuvable : {path}")
    return project_mod.load_project(path)


def _maybe_open_gui(project_path: str, do_edit: bool,
                    copies: list[str] | None = None) -> int:
    """Ouvre l'interface graphique sur le projet si do_edit, sinon ne fait rien.

    Si ``copies`` est fourni, les copies sont chargées et corrigées
    automatiquement à l'ouverture (onglet Correction).

    Retourne le code de retour de la GUI (0 si non ouverte).
    """
    if not do_edit:
        return 0
    try:
        from .ui.app import run as gui_run
    except ImportError as e:
        print(f"Interface graphique indisponible ({e}) : --edit ignoré.",
              file=sys.stderr)
        return 0
    print(f"Ouverture de l'interface graphique : {project_path}")
    return gui_run(project_path=project_path, copies=copies)



def cmd_open(args: argparse.Namespace) -> int:
    """Ouvre et valide un projet JSON, affiche un résumé."""
    project = _load_project(args.project)
    n_ex = len(project.structure)
    n_q = sum(len(e.questions) for e in project.structure)
    n_c = sum(len(q.choices) for e in project.structure for q in e.questions)
    n_v = len([k for k in project.variants if k not in ("p", "l")])
    print(f"Projet : {args.project}")
    print(f"  Exercices : {n_ex}")
    print(f"  Questions : {n_q}")
    print(f"  Choix : {n_c}")
    print(f"  Variantes générées : {n_v}")
    print(f"  Étudiants : {len(project.students)}")
    return _maybe_open_gui(args.project, getattr(args, "edit", False))


def cmd_variants(args: argparse.Namespace) -> int:
    """Génère les variantes d'un projet et les sauvegarde dans le JSON."""
    project = _load_project(args.project)
    ids, failed = generator.generate_all(project, retry=args.retry)
    if failed:
        print(f"Variantes en échec : {failed}", file=sys.stderr)
    print(f"Variantes générées : {ids}")
    # Sauvegarde le projet mis à jour (variantes + ids).
    save_path = args.save_project or args.project
    project_mod.save_project(project, save_path)
    print(f"Projet sauvegardé : {save_path}")
    return _maybe_open_gui(args.project, getattr(args, "edit", False))


def cmd_pdf(args: argparse.Namespace) -> int:
    """Génère le sujet PDF à partir des variantes existantes d'un projet."""
    project = _load_project(args.project)
    # --regenerate : régénère les variantes avant de faire le PDF.
    if getattr(args, "regenerate", False):
        ids, failed = generator.generate_all(project, retry=True)
        if failed:
            print(f"Variantes en échec : {failed}", file=sys.stderr)
        print(f"Variantes régénérées : {ids}")
    if not any(k not in ("p", "l") for k in project.variants):
        raise SystemExit("Le projet ne contient pas de variantes générées. "
                         "Lancez d'abord 'qcm-papier variants'.")
    out = args.output
    if not out:
        out = (project.settings.evaluation_short or "sujet") + ".pdf"
    # Forcer l'extension .pdf pour éviter d'écraser un fichier existant
    if not out.endswith('.pdf'):
        out += '.pdf'
    pdf_writer.generate_pdf(project, out, per_student=args.per_student)
    print(f"Sujet PDF généré : {out}")
    return _maybe_open_gui(args.project, getattr(args, "edit", False))


def cmd_generate(args: argparse.Namespace) -> int:
    """Génère le sujet PDF à partir d'un projet (variantes + PDF en un appel)."""
    project = _load_project(args.project)
    # Génère les variantes si nécessaire ou si --regenerate est demandé.
    need_gen = (not any(k not in ("p", "l") for k in project.variants)
               or getattr(args, "regenerate", False))
    if need_gen:
        ids, failed = generator.generate_all(project, retry=args.retry)
        if failed:
            print(f"Variantes en échec : {failed}", file=sys.stderr)
        print(f"Variantes générées : {ids}")
    # Génère le PDF.
    out = args.output
    if not out:
        out = (project.settings.evaluation_short or "sujet") + ".pdf"
    # Forcer l'extension .pdf pour éviter d'écraser un fichier existant
    if not out.endswith('.pdf'):
        out += '.pdf'
    pdf_writer.generate_pdf(project, out, per_student=args.per_student)
    print(f"Sujet PDF généré : {out}")
    # Sauvegarde le projet mis à jour (variantes + ids).
    if args.save_project:
        project_mod.save_project(project, args.save_project)
        print(f"Projet sauvegardé : {args.save_project}")
    return _maybe_open_gui(args.project, getattr(args, "edit", False))


def cmd_correct(args: argparse.Namespace) -> int:
    """Corrige un lot de copies et exporte les notes."""
    project = _load_project(args.project)
    if not any(k not in ("p", "l") for k in project.variants):
        raise SystemExit("Le projet ne contient pas de variantes générées. "
                         "Lancez d'abord 'qcm-papier generate'.")

    # Table étudiants (optionnelle, pour la levée d'anonymat).
    if args.students:
        project.students = scodoc.load_students_table(args.students)
        print(f"Table étudiants chargée : {len(project.students)} étudiants")

    # Charge les copies (fichiers ou répertoire).
    copies: list[str] = []
    for path in args.copies:
        if os.path.isdir(path):
            for ext in (".pdf", ".png", ".jpg", ".jpeg", ".bmp"):
                copies.extend(sorted(Path(path).glob(f"**/*{ext}")))
        elif os.path.isfile(path):
            copies.append(path)
    if not copies:
        raise SystemExit("Aucune copie à corriger.")

    print(f"Correction de {len(copies)} fichier(s)...")
    notes: dict[str, float] = {}
    corrected_pages: list = []
    for copy_path in copies:
        try:
            pages = scanner.load_pages_from_file(copy_path, dpi=args.dpi)
        except Exception as e:
            print(f"  {copy_path} : ERREUR de chargement ({e})", file=sys.stderr)
            continue
        for page in pages:
            ok = scanner.auto_check(page, project,
                                     clair=getattr(args, "clair", 140))
            if not ok:
                print(f"  {copy_path} : correction échouée (alignement ?)",
                      file=sys.stderr)
                continue
            if page.student_eid is not None and page.value is not None:
                notes[page.student_eid] = page.value
            elif page.student_id is not None and page.value is not None:
                notes[page.student_id] = page.value
            corrected_pages.append((copy_path, page))
            print(f"  {copy_path} : variante {page.variant_id}, "
                  f"étudiant {page.student_id}, note {page.value}/{page.total}"
                  f" {'(complète)' if page.complete else '(incomplète)'}")

    # Rendu visuel des pages corrigées (overlay vert/rouge).
    if getattr(args, "render", None) is not None:
        render_dir = args.render if args.render else os.path.dirname(os.path.abspath(copies[0]))
        n = 0
        for copy_path, page in corrected_pages:
            img = scanner.render_marked_page(page)
            if img is None:
                continue
            base = os.path.splitext(os.path.basename(copy_path))[0]
            suffix = f"_v{page.variant_id}_{page.student_id or 'anonyme'}"
            out = os.path.join(render_dir, f"{base}{suffix}.png")
            img.save(out)
            n += 1
            print(f"  Page corrigée rendue : {out}")
        print(f"{n} page(s) rendue(s) dans {render_dir}")

    # Export Scodoc (optionnel).
    if args.scodoc_input:
        out = args.output or "notes_scodoc.xlsx"
        count = scodoc.export_scodoc_notes(args.scodoc_input, out, notes,
                                          note_max=args.note_max,
                                          notemax=project.settings.NOTEMAX
                                          if hasattr(project.settings, "NOTEMAX")
                                          else 20.0)
        print(f"Notes exportées : {count} → {out}")
    elif args.output:
        # Export CSV simple.
        import csv
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["eid", "note", "total"])
            for eid, note in notes.items():
                w.writerow([eid, note, 20.0])
        print(f"Notes exportées : {len(notes)} → {args.output}")
    else:
        print(f"\nRécapitulatif ({len(notes)} notes) :")
        for eid, note in notes.items():
            print(f"  {eid}: {note}")
    return _maybe_open_gui(args.project, getattr(args, "edit", False),
                          copies=copies)


cmd_check = cmd_open  # alias rétro-compatible (l'ancienne commande 'check')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qcm-papier",
        description="Générateur/Correcteur de QCM papier (portage Python du "
                    "code HTML+JS de l'Université Lyon 1).",
    )
    sub = parser.add_subparsers(dest="command")

    # open : ouvrir/valider un projet JSON
    p_open = sub.add_parser("open", help="Ouvrir et valider un projet JSON")
    p_open.add_argument("--project", "-p", required=True,
                        help="Fichier projet JSON")
    p_open.add_argument("--edit", action="store_true",
                        help="Ouvrir l'interface graphique sur le projet")
    p_open.set_defaults(func=cmd_open)

    # variants : générer les variantes et les sauvegarder
    p_var = sub.add_parser("variants",
                           help="Générer les variantes et les sauvegarder dans le JSON")
    p_var.add_argument("--project", "-p", required=True,
                       help="Fichier projet JSON")
    p_var.add_argument("--save-project", help="Sauvegarder le projet mis à jour "
                       "(par défaut : le fichier d'entrée)")
    p_var.add_argument("--retry", action="store_true", default=True,
                       help="Réessayer avec un nouvel id si une variante échoue")
    p_var.add_argument("--no-retry", dest="retry", action="store_false",
                       help="Ne pas réessayer en cas d'échec")
    p_var.add_argument("--edit", action="store_true",
                       help="Ouvrir l'interface graphique sur le projet après génération des variantes")
    p_var.set_defaults(func=cmd_variants)

    # pdf : générer le PDF à partir des variantes existantes
    p_pdf = sub.add_parser("pdf", help="Générer le PDF à partir des variantes existantes")
    p_pdf.add_argument("--project", "-p", required=True,
                       help="Fichier projet JSON (avec variantes générées)")
    p_pdf.add_argument("--output", "-o", help="Fichier PDF de sortie")
    p_pdf.add_argument("--per-student", action="store_true",
                       help="Générer une copie par étudiant (au lieu d'une par variante)")
    p_pdf.add_argument("--edit", action="store_true",
                       help="Ouvrir l'interface graphique sur le projet après génération du PDF")
    p_pdf.add_argument("--regenerate", action="store_true",
                       help="Régénérer les variantes avant de générer le PDF")
    p_pdf.set_defaults(func=cmd_pdf)

    # generate : tout en un (rétro-compatible)
    p_gen = sub.add_parser("generate", help="Générer le sujet PDF (variantes + PDF en un appel)")
    p_gen.add_argument("--project", "-p", required=True,
                       help="Fichier projet JSON")
    p_gen.add_argument("--output", "-o", help="Fichier PDF de sortie")
    p_gen.add_argument("--retry", action="store_true", default=True,
                       help="Réessayer avec un nouvel id si une variante échoue")
    p_gen.add_argument("--no-retry", dest="retry", action="store_false",
                       help="Ne pas réessayer en cas d'échec")
    p_gen.add_argument("--per-student", action="store_true",
                       help="Générer une copie par étudiant (au lieu d'une par variante)")
    p_gen.add_argument("--save-project", help="Sauvegarder le projet mis à jour")
    p_gen.add_argument("--edit", action="store_true",
                       help="Ouvrir l'interface graphique sur le projet après génération du PDF")
    p_gen.add_argument("--regenerate", action="store_true",
                       help="Régénérer les variantes même si elles existent déjà")
    p_gen.set_defaults(func=cmd_generate)

    # correct
    p_cor = sub.add_parser("correct", help="Corriger des copies scannées")
    p_cor.add_argument("--project", "-p", required=True,
                       help="Fichier projet JSON (avec variantes générées)")
    p_cor.add_argument("--copies", "-c", nargs="+", required=True,
                       help="Fichiers ou répertoires de copies (PDF/images)")
    p_cor.add_argument("--students", help="Table étudiants Scodoc (XLS/XLSX)")
    p_cor.add_argument("--scodoc-input", help="Feuille de notes Scodoc à remplir")
    p_cor.add_argument("--output", "-o", help="Fichier de sortie (notes)")
    p_cor.add_argument("--dpi", type=int, default=150,
                       help="Résolution de rendu des PDF (défaut 150)")
    p_cor.add_argument("--note-max", type=float, default=20.0,
                       help="Note maximale de l'échelle Scodoc (défaut 20)")
    p_cor.add_argument("--clair", type=int, default=140,
                       help="Seuil de détection des cases cochées (défaut 140 ; "
                            "augmenter pour des scans plus sombres)")
    p_cor.add_argument("--render", nargs="?", const="", default=None,
                       help="Rendre les pages corrigées en PNG (overlay vert/rouge) ; "
                            "valeur optionnelle = répertoire de sortie (défaut : répertoire des copies)")
    p_cor.add_argument("--edit", action="store_true",
                       help="Ouvrir l'interface graphique après correction (onglet Correction avec les pages corrigées)")
    p_cor.set_defaults(func=cmd_correct)

    # check
    p_chk = sub.add_parser("check", help="Valider un projet")
    p_chk.add_argument("--project", "-p", required=True)
    p_chk.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
