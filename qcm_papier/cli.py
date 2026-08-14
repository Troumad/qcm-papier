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


def cmd_generate(args: argparse.Namespace) -> int:
    """Génère le sujet PDF à partir d'un projet."""
    project = _load_project(args.project)
    # Génère les variantes si nécessaire.
    if not any(k not in ("p", "l") for k in project.variants):
        ids, failed = generator.generate_all(project, retry=args.retry)
        if failed:
            print(f"Variantes en échec : {failed}", file=sys.stderr)
        print(f"Variantes générées : {ids}")
    # Génère le PDF.
    out = args.output
    if not out:
        out = (project.settings.evaluation_short or "sujet") + ".pdf"
    pdf_writer.generate_pdf(project, out, per_student=args.per_student)
    print(f"Sujet PDF généré : {out}")
    # Sauvegarde le projet mis à jour (variantes + ids).
    if args.save_project:
        project_mod.save_project(project, args.save_project)
        print(f"Projet sauvegardé : {args.save_project}")
    return 0


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
    for copy_path in copies:
        try:
            pages = scanner.load_pages_from_file(copy_path, dpi=args.dpi)
        except Exception as e:
            print(f"  {copy_path} : ERREUR de chargement ({e})", file=sys.stderr)
            continue
        for page in pages:
            ok = scanner.auto_check(page, project)
            if not ok:
                print(f"  {copy_path} : correction échouée (alignement ?)",
                      file=sys.stderr)
                continue
            if page.student_eid is not None and page.value is not None:
                notes[page.student_eid] = page.value
            elif page.student_id is not None and page.value is not None:
                notes[page.student_id] = page.value
            print(f"  {copy_path} : variante {page.variant_id}, "
                  f"étudiant {page.student_id}, note {page.value}/{page.total}"
                  f" {'(complète)' if page.complete else '(incomplète)'}")

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
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Valide qu'un projet est bien formé."""
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
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qcm-papier",
        description="Générateur/Correcteur de QCM papier (portage Python du "
                    "code HTML+JS de l'Université Lyon 1).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    p_gen = sub.add_parser("generate", help="Générer le sujet PDF")
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
    p_cor.set_defaults(func=cmd_correct)

    # check
    p_chk = sub.add_parser("check", help="Valider un projet")
    p_chk.add_argument("--project", "-p", required=True)
    p_chk.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
