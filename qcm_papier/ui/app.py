"""Fenêtre principale de l'application GTK 4.

Organisée en onglets comme le code original :
* **Structure** : éditeur d'exercices/questions/choix + informations du QCM.
* **Génération** : génération des variantes et du PDF sujet.
* **Correction** : chargement des copies, correction, export Scodoc.

Les actions de menu (Nouveau, Ouvrir, Enregistrer) gèrent la persistance du
projet au format JSON.

Écrit pour GTK 4 (PyGObject) : utilise ``append``/``present`` au lieu de
``add``/``show_all`` de GTK 3, et ``Gtk.FileChooserNative`` au lieu du
``Gtk.FileChooserDialog`` supprimé en GTK 4.
"""

from __future__ import annotations

import os

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .. import generator, pdf_writer, project as project_mod, scanner, scodoc
from ..model import Project
from .editor import StructureEditor


def _file_dialog(parent, title: str, action, filters=None, initial_name=None):
    """Crée un sélecteur de fichier natif (GTK 4).

    ``action`` vaut ``Gtk.FileChooserAction.OPEN`` ou ``.SAVE``.
    Retourne le chemin choisi ou ``None``.
    """
    dialog = Gtk.FileChooserNative.new(title, parent, action, None, None)
    if filters:
        for name, patterns in filters:
            filt = Gtk.FileFilter()
            filt.set_name(name)
            for p in patterns:
                filt.add_pattern(p)
            dialog.add_filter(filt)
    if initial_name and action == Gtk.FileChooserAction.SAVE:
        dialog.set_current_name(initial_name)

    # GTK4: FileChooserNative utilise des signaux, pas open()/save()
    path = [None]  # Stockage du chemin dans une liste pour le callback

    def on_response(native, response):
        if response == Gtk.ResponseType.ACCEPT:
            file_obj = dialog.get_file()
            path[0] = file_obj.get_path() if file_obj else None
        else:
            path[0] = None
        dialog.destroy()

    dialog.connect("response", on_response)
    dialog.present()  # Affiche le dialogue (GTK4)
    from gi.repository import GLib
    GLib.MainLoop().run()  # Attend la réponse (modal)
    return path[0]


class QcmWindow(Gtk.ApplicationWindow):
    """Fenêtre principale de l'application."""

    def __init__(self, **kwargs):
        super().__init__(title="Générateur/Correcteur de QCM papier",
                         default_width=1000, default_height=700, **kwargs)
        self.project = Project()

        # Barre d'en-tête.
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        self.set_titlebar(header)

        btn_new = Gtk.Button(label="Nouveau")
        btn_new.connect("clicked", self._on_new)
        btn_open = Gtk.Button(label="Ouvrir")
        btn_open.connect("clicked", self._on_open)
        btn_save = Gtk.Button(label="Enregistrer")
        btn_save.connect("clicked", self._on_save)
        header.pack_start(btn_new)
        header.pack_start(btn_open)
        header.pack_start(btn_save)

        # Notebook (onglets).
        self.notebook = Gtk.Notebook()
        self.set_child(self.notebook)

        self._build_structure_tab()
        self._build_generate_tab()
        self._build_marking_tab()

        self._last_notes: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Onglet Structure
    # ------------------------------------------------------------------

    def _build_structure_tab(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # Informations du QCM (champs principaux).
        info_grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        self._entries: dict[str, Gtk.Entry] = {}
        fields = [
            ("establishment", "Établissement"),
            ("formation", "Formation"),
            ("year", "Année (dans code-barre)"),
            ("module_short", "Module (abrégé, code-barre)"),
            ("evaluation_short", "Évaluation (abrégé, code-barre)"),
            ("date", "Date"),
            ("duration", "Durée"),
        ]
        for i, (attr, label) in enumerate(fields):
            info_grid.attach(Gtk.Label(label=label), 0, i, 1, 1)
            entry = Gtk.Entry()
            entry.set_hexpand(True)
            entry.set_text(getattr(self.project.settings, attr))
            entry.connect("changed",
                          lambda e, a=attr: setattr(self.project.settings, a, e.get_text()))
            info_grid.attach(entry, 1, i, 1, 1)
            self._entries[attr] = entry
        box.append(info_grid)

        # Éditeur de structure.
        self.editor = StructureEditor(self.project, on_change=self._on_structure_changed)
        box.append(self.editor)

        self.notebook.append_page(box, Gtk.Label(label="Structure"))

    def _on_structure_changed(self) -> None:
        self.project.settings.modified = True

    # ------------------------------------------------------------------
    # Onglet Génération
    # ------------------------------------------------------------------

    def _build_generate_tab(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        self.spin_students = Gtk.SpinButton.new_with_range(1, 1000, 1)
        self.spin_students.set_value(self.project.settings.generate_students)
        self.spin_count = Gtk.SpinButton.new_with_range(1, 4096, 1)
        self.spin_count.set_value(self.project.settings.generate_count)
        self.entry_variants = Gtk.Entry()
        self.entry_variants.set_placeholder_text("Ids variantes (séparés par ;)")
        grid.attach(Gtk.Label(label="Nombre d'étudiants :"), 0, 0, 1, 1)
        grid.attach(self.spin_students, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Nombre de variantes :"), 0, 1, 1, 1)
        grid.attach(self.spin_count, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="Ids variantes :"), 0, 2, 1, 1)
        grid.attach(self.entry_variants, 1, 2, 1, 1)
        box.append(grid)

        btn_generate = Gtk.Button(label="Générer les variantes")
        btn_generate.connect("clicked", self._on_generate_variants)
        box.append(btn_generate)

        btn_pdf = Gtk.Button(label="Générer le PDF")
        btn_pdf.connect("clicked", self._on_generate_pdf)
        box.append(btn_pdf)

        self.generate_status = Gtk.Label(label="")
        box.append(self.generate_status)

        self.notebook.append_page(box, Gtk.Label(label="Génération"))

    def _on_generate_variants(self, _btn) -> None:
        self.project.settings.generate_students = int(self.spin_students.get_value())
        self.project.settings.generate_count = int(self.spin_count.get_value())
        self.project.settings.generate_variants = self.entry_variants.get_text()
        ids, failed = generator.generate_all(self.project, retry=True)
        self.entry_variants.set_text(";".join(str(i) for i in ids))
        msg = f"{len(ids)} variantes générées."
        if failed:
            msg += f" {len(failed)} en échec."
        self.generate_status.set_text(msg)

    def _on_generate_pdf(self, _btn) -> None:
        variant_keys = [k for k in self.project.variants if k not in ("p", "l")]
        if not variant_keys:
            self.generate_status.set_text("Aucune variante : générez d'abord les variantes.")
            return
        name = self.project.settings.evaluation_short or "sujet"
        path = _file_dialog(self, "Enregistrer le PDF",
                            Gtk.FileChooserAction.SAVE,
                            initial_name=f"{name}.pdf")
        if path is None:
            return
        try:
            pdf_writer.generate_pdf(self.project, path)
            self.generate_status.set_text(f"PDF généré : {path}")
        except Exception as e:
            self.generate_status.set_text(f"Erreur : {e}")

    # ------------------------------------------------------------------
    # Onglet Correction
    # ------------------------------------------------------------------

    def _build_marking_tab(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # Chargement des copies.
        files_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_load = Gtk.Button(label="Charger des copies…")
        btn_load.connect("clicked", self._on_load_copies)
        btn_correct = Gtk.Button(label="Lancer la correction")
        btn_correct.connect("clicked", self._on_correct)
        btn_students = Gtk.Button(label="Table étudiants (Scodoc)…")
        btn_students.connect("clicked", self._on_load_students)
        btn_export = Gtk.Button(label="Exporter les notes Scodoc…")
        btn_export.connect("clicked", self._on_export_scodoc)
        files_box.append(btn_load)
        files_box.append(btn_correct)
        files_box.append(btn_students)
        files_box.append(btn_export)
        box.append(files_box)

        self.copies: list[str] = []
        self.copies_store = Gtk.ListStore(str)
        tree = Gtk.TreeView(model=self.copies_store)
        tree.append_column(Gtk.TreeViewColumn("Copies", Gtk.CellRendererText(), text=0))
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_child(tree)
        box.append(scroll)

        self.marking_status = Gtk.Label(label="")
        box.append(self.marking_status)

        # Store des résultats.
        self.results_store = Gtk.ListStore(str, str, str, str, str)
        results_tree = Gtk.TreeView(model=self.results_store)
        for i, title in enumerate(["Fichier", "Variante", "Étudiant", "Note", "Statut"]):
            results_tree.append_column(
                Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i))
        scroll2 = Gtk.ScrolledWindow()
        scroll2.set_vexpand(True)
        scroll2.set_child(results_tree)
        box.append(scroll2)

        self.notebook.append_page(box, Gtk.Label(label="Correction"))

    def _on_load_copies(self, _btn) -> None:
        path = _file_dialog(self, "Choisir les copies",
                            Gtk.FileChooserAction.OPEN,
                            filters=[("PDF et images", ["*.pdf", "*.png",
                                                         "*.jpg", "*.jpeg"])])
        if path is None:
            return
        # FileChooserNative ne gère pas la multi-sélection ; on prend un fichier.
        # Pour un répertoire, l'utilisateur peut lancer la correction sur un dossier
        # via la ligne de commande (qcm-papier correct -c dossier/).
        self.copies = [path]
        self.copies_store.clear()
        self.copies_store.append([os.path.basename(path)])
        self.marking_status.set_text("1 copie chargée. (Pour plusieurs fichiers, "
                                      "utilisez la CLI : qcm-papier correct -c ...)")

    def _on_load_students(self, _btn) -> None:
        path = _file_dialog(self, "Table étudiants Scodoc",
                            Gtk.FileChooserAction.OPEN,
                            filters=[("Excel", ["*.xlsx", "*.xls"])])
        if path is None:
            return
        try:
            self.project.students = scodoc.load_students_table(path)
            self.marking_status.set_text(
                f"{len(self.project.students)} étudiant(s) chargé(s).")
        except Exception as e:
            self.marking_status.set_text(f"Erreur : {e}")

    def _on_correct(self, _btn) -> None:
        variant_keys = [k for k in self.project.variants if k not in ("p", "l")]
        if not variant_keys:
            self.marking_status.set_text(
                "Aucune variante : chargez un projet avec variantes générées.")
            return
        if not self.copies:
            self.marking_status.set_text("Aucune copie chargée.")
            return
        self.results_store.clear()
        notes: dict[str, float] = {}
        n_ok = 0
        for copy_path in self.copies:
            try:
                pages = scanner.load_pages_from_file(copy_path, dpi=150)
            except Exception as e:
                self.results_store.append([os.path.basename(copy_path), "",
                                            "", "", f"Erreur : {e}"])
                continue
            for page in pages:
                ok = scanner.auto_check(page, self.project)
                if ok:
                    n_ok += 1
                    eid = page.student_eid or page.student_id or ""
                    note = page.value if page.value is not None else 0.0
                    if eid:
                        notes[eid] = note
                    self.results_store.append([
                        os.path.basename(copy_path),
                        str(page.variant_id or ""),
                        page.student_id or "",
                        f"{note:.2f}",
                        "complète" if page.complete else "incomplète",
                    ])
                else:
                    self.results_store.append([os.path.basename(copy_path), "",
                                                "", "", "Échec alignement"])
        self._last_notes = notes
        self.marking_status.set_text(f"{n_ok} copie(s) corrigée(s).")

    def _on_export_scodoc(self, _btn) -> None:
        if not self._last_notes:
            self.marking_status.set_text("Aucune note à exporter : corrigez d'abord.")
            return
        path_in = _file_dialog(self, "Feuille de notes Scodoc (entrée)",
                                Gtk.FileChooserAction.OPEN,
                                filters=[("Excel", ["*.xlsx", "*.xls"])])
        if path_in is None:
            return
        path_out = _file_dialog(self, "Enregistrer les notes",
                                 Gtk.FileChooserAction.SAVE,
                                 initial_name="notes_scodoc.xlsx")
        if path_out is None:
            return
        try:
            count = scodoc.export_scodoc_notes(path_in, path_out, self._last_notes)
            self.marking_status.set_text(
                f"{count} note(s) exportée(s) → {path_out}")
        except Exception as e:
            self.marking_status.set_text(f"Erreur : {e}")

    # ------------------------------------------------------------------
    # Menu : Nouveau / Ouvrir / Enregistrer
    # ------------------------------------------------------------------

    def _on_new(self, _btn) -> None:
        self.project = Project()
        self.editor.project = self.project
        self.editor._fill_tree()
        self.copies_store.clear()
        self.results_store.clear()
        self.generate_status.set_text("Nouveau projet.")

    def _on_open(self, _btn) -> None:
        path = _file_dialog(self, "Ouvrir un projet", Gtk.FileChooserAction.OPEN,
                            filters=[("Projet JSON", ["*.json"])])
        if path is None:
            return
        try:
            self.project = project_mod.load_project(path)
            self.editor.project = self.project
            self.editor._fill_tree()
            # Synchroniser les champs d'info.
            for attr, entry in self._entries.items():
                entry.set_text(getattr(self.project.settings, attr))
            self.entry_variants.set_text(self.project.settings.generate_variants)
            self.spin_students.set_value(self.project.settings.generate_students)
            self.spin_count.set_value(self.project.settings.generate_count)
            self.generate_status.set_text(f"Projet chargé : {path}")
        except Exception as e:
            self.generate_status.set_text(f"Erreur : {e}")

    def _on_save(self, _btn) -> None:
        name = self.project.settings.evaluation_short or "qcm_papier"
        path = _file_dialog(self, "Enregistrer le projet",
                            Gtk.FileChooserAction.SAVE,
                            initial_name=f"{name}.json")
        if path is None:
            return
        try:
            project_mod.save_project(self.project, path)
            self.generate_status.set_text(f"Projet enregistré : {path}")
        except Exception as e:
            self.generate_status.set_text(f"Erreur : {e}")


class QcmApplication(Gtk.Application):
    """Application GTK 4."""

    def __init__(self):
        super().__init__(application_id="org.qcm_papier")

    def do_activate(self):
        win = QcmWindow(application=self)
        win.present()


def run(argv: list[str] | None = None) -> int:
    """Lance l'interface graphique."""
    app = QcmApplication()
    return app.run(argv if argv is not None else [])
