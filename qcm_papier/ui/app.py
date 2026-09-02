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
from gi.repository import Gtk, Gdk

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

    # GTK4: FileChooserNative utilise show() + signal response
    path = [None]
    from gi.repository import GLib
    loop = GLib.MainLoop()

    def on_response(native, response):
        if response == Gtk.ResponseType.ACCEPT:
            file_obj = dialog.get_file()
            path[0] = file_obj.get_path() if file_obj else None
        dialog.destroy()
        loop.quit()

    dialog.connect("response", on_response)
    dialog.show()
    loop.run()
    return path[0]


class QcmWindow(Gtk.ApplicationWindow):
    """Fenêtre principale de l'application."""

    def __init__(self, **kwargs):
        super().__init__(title="Générateur/Correcteur de QCM papier",
                        default_width=1000, default_height=700, **kwargs)
        
                
        self.project = Project()

        # Crée un HeaderBar manuellement
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        self.set_titlebar(header)  # ← **Définir le HeaderBar**

        # Ajoute un Label pour le titre
        #self.title_label = Gtk.Label(label="Générateur/Correcteur de QCM papier")
        #header.set_title_widget(self.title_label)  # ← **Place le Label au centre**

        # Ajoute les boutons
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
        
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(b"""
            .suggestion {
                color: #666;
                font-style: italic;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )       

        self._build_info_tab()
        self._build_structure_tab()
        self._build_generate_tab()
        self._build_marking_tab()

        self._last_notes: dict[str, float] = {}
        # Ouverture sur l'onglet Structure
        self.notebook.set_current_page(1)  # 0=Informations, 1=Structure, 2=Génération, 3=Correction

    # ------------------------------------------------------------------
    # Onglet Structure
    # ------------------------------------------------------------------

    def _build_info_tab(self) -> None:
        """Onglet Informations : tous les champs du QCM avec valeurs par défaut."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # --- Ligne 1 : Établissement, Institut, Formation ---
        grid1 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid1.attach(Gtk.Label(label="Établissement :"), 0, 0, 1, 1)
        self.entry_establishment = Gtk.Entry()
        self.entry_establishment.set_hexpand(True)
        default_establishment = self.project.settings.establishment or "Université Lyon 1"
        self.entry_establishment.set_text(default_establishment)
        self.entry_establishment.connect("changed",
            lambda e: setattr(self.project.settings, "establishment", e.get_text()))
        if not self.project.settings.establishment:
            self.entry_establishment.get_style_context().add_class("suggestion")
        grid1.attach(self.entry_establishment, 1, 0, 1, 1)

        grid1.attach(Gtk.Label(label="Institut :"), 2, 0, 1, 1)
        self.entry_institute = Gtk.Entry()
        self.entry_institute.set_hexpand(True)
        default_institute = self.project.settings.institute or "IUT LYON 1"
        self.entry_institute.set_text(default_institute)
        self.entry_institute.connect("changed",
            lambda e: setattr(self.project.settings, "institute", e.get_text()))
        if not self.project.settings.institute:
            self.entry_institute.get_style_context().add_class("suggestion")
        grid1.attach(self.entry_institute, 3, 0, 1, 1)

        grid1.attach(Gtk.Label(label="Formation :"), 4, 0, 1, 1)
        self.entry_formation = Gtk.Entry()
        self.entry_formation.set_hexpand(True)
        default_formation = self.project.settings.formation or "Département GEii"
        self.entry_formation.set_text(default_formation)
        self.entry_formation.connect("changed",
            lambda e: setattr(self.project.settings, "formation", e.get_text()))
        if not self.project.settings.formation:
            self.entry_formation.get_style_context().add_class("suggestion")
        grid1.attach(self.entry_formation, 5, 0, 1, 1)
        box.append(grid1)

        # --- Ligne 2 : Année, Semestre, Unité d'enseignement ---
        grid2 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid2.attach(Gtk.Label(label="Année :"), 0, 0, 1, 1)
        self.entry_year = Gtk.Entry()
        self.entry_year.set_hexpand(True)
        default_year = self.project.settings.year or "2026"
        self.entry_year.set_text(default_year)
        self.entry_year.connect("changed",
            lambda e: setattr(self.project.settings, "year", e.get_text()))
        if not self.project.settings.year:
            self.entry_year.get_style_context().add_class("suggestion")
        grid2.attach(self.entry_year, 1, 0, 1, 1)

        grid2.attach(Gtk.Label(label="Semestre :"), 2, 0, 1, 1)
        self.entry_semester = Gtk.Entry()
        self.entry_semester.set_hexpand(True)
        default_semester = self.project.settings.semester or "S1"
        self.entry_semester.set_text(default_semester)
        self.entry_semester.connect("changed",
            lambda e: setattr(self.project.settings, "semester", e.get_text()))
        if not self.project.settings.semester:
            self.entry_semester.get_style_context().add_class("suggestion")
        grid2.attach(self.entry_semester, 3, 0, 1, 1)

        grid2.attach(Gtk.Label(label="Unité d'enseignement :"), 4, 0, 1, 1)
        self.entry_teaching_unit = Gtk.Entry()
        self.entry_teaching_unit.set_hexpand(True)
        default_teaching_unit = self.project.settings.teaching_unit or "UE3"
        self.entry_teaching_unit.set_text(default_teaching_unit)
        self.entry_teaching_unit.connect("changed",
            lambda e: setattr(self.project.settings, "teaching_unit", e.get_text()))
        if not self.project.settings.teaching_unit:
            self.entry_teaching_unit.get_style_context().add_class("suggestion")
        grid2.attach(self.entry_teaching_unit, 5, 0, 1, 1)
        box.append(grid2)

        # --- Ligne 3 : Module complet, Module abrégé ---
        grid3 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid3.attach(Gtk.Label(label="Module complet :"), 0, 0, 1, 1)
        self.entry_module_full = Gtk.Entry()
        self.entry_module_full.set_hexpand(True)
        default_module_full = self.project.settings.module_full or "Mathématiques"
        self.entry_module_full.set_text(default_module_full)
        self.entry_module_full.connect("changed",
            lambda e: setattr(self.project.settings, "module_full", e.get_text()))
        if not self.project.settings.module_full:
            self.entry_module_full.get_style_context().add_class("suggestion")
        grid3.attach(self.entry_module_full, 1, 0, 1, 1)

        grid3.attach(Gtk.Label(label="Module abrégé :"), 2, 0, 1, 1)
        self.entry_module_short = Gtk.Entry()
        self.entry_module_short.set_hexpand(True)
        default_module_short = self.project.settings.module_short or "OML1"
        self.entry_module_short.set_text(default_module_short)
        self.entry_module_short.connect("changed",
            lambda e: setattr(self.project.settings, "module_short", e.get_text()))
        if not self.project.settings.module_short:
            self.entry_module_short.get_style_context().add_class("suggestion")
        grid3.attach(self.entry_module_short, 3, 0, 1, 1)
        box.append(grid3)

        # --- Ligne 4 : Évaluation complète, Évaluation abrégée ---
        grid4 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid4.attach(Gtk.Label(label="Évaluation complète :"), 0, 0, 1, 1)
        self.entry_evaluation_full = Gtk.Entry()
        self.entry_evaluation_full.set_hexpand(True)
        default_evaluation_full = self.project.settings.evaluation_full or "QCM Mathématiques"
        self.entry_evaluation_full.set_text(default_evaluation_full)
        self.entry_evaluation_full.connect("changed",
            lambda e: setattr(self.project.settings, "evaluation_full", e.get_text()))
        if not self.project.settings.evaluation_full:
            self.entry_evaluation_full.get_style_context().add_class("suggestion")
        grid4.attach(self.entry_evaluation_full, 1, 0, 1, 1)

        grid4.attach(Gtk.Label(label="Évaluation abrégée :"), 2, 0, 1, 1)
        self.entry_evaluation_short = Gtk.Entry()
        self.entry_evaluation_short.set_hexpand(True)
        default_evaluation_short = self.project.settings.evaluation_short or "OML1"
        self.entry_evaluation_short.set_text(default_evaluation_short)
        self.entry_evaluation_short.connect("changed",
            lambda e: setattr(self.project.settings, "evaluation_short", e.get_text()))
        if not self.project.settings.evaluation_short:
            self.entry_evaluation_short.get_style_context().add_class("suggestion")
        grid4.attach(self.entry_evaluation_short, 3, 0, 1, 1)
        box.append(grid4)

        # --- Ligne 5 : Enseignants, Date, Durée ---
        grid5 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid5.attach(Gtk.Label(label="Enseignants :"), 0, 0, 1, 1)
        self.entry_teachers = Gtk.Entry()
        self.entry_teachers.set_hexpand(True)
        default_teachers = self.project.settings.teachers or "BS"
        self.entry_teachers.set_text(default_teachers)
        self.entry_teachers.connect("changed",
            lambda e: setattr(self.project.settings, "teachers", e.get_text()))
        if not self.project.settings.teachers:
            self.entry_teachers.get_style_context().add_class("suggestion")
        grid5.attach(self.entry_teachers, 1, 0, 1, 1)

        grid5.attach(Gtk.Label(label="Date :"), 2, 0, 1, 1)
        self.entry_date = Gtk.Entry()
        self.entry_date.set_hexpand(True)
        default_date = self.project.settings.date or "09/10/2026"
        self.entry_date.set_text(default_date)
        self.entry_date.connect("changed",
            lambda e: setattr(self.project.settings, "date", e.get_text()))
        if not self.project.settings.date:
            self.entry_date.get_style_context().add_class("suggestion")
        grid5.attach(self.entry_date, 3, 0, 1, 1)

        grid5.attach(Gtk.Label(label="Durée :"), 4, 0, 1, 1)
        self.entry_duration = Gtk.Entry()
        self.entry_duration.set_hexpand(True)
        default_duration = self.project.settings.duration or "1h"
        self.entry_duration.set_text(default_duration)
        self.entry_duration.connect("changed",
            lambda e: setattr(self.project.settings, "duration", e.get_text()))
        if not self.project.settings.duration:
            self.entry_duration.get_style_context().add_class("suggestion")
        grid5.attach(self.entry_duration, 5, 0, 1, 1)
        box.append(grid5)

        self.notebook.append_page(box, Gtk.Label(label="Informations"))

    def _build_structure_tab(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

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

        success, failed = generator.generate_all(self.project, retry=True)

        # 🔧 CORRECTION: Stocker TOUS les IDs (succès + échecs + remplacements)
        all_ids = success + failed
        self.entry_variants.set_text(";".join(str(i) for i in all_ids))

        # ✅ Message exact : seul le nombre de succès est affiché
        msg = f"{len(success)} variantes générées."
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
        self.set_title("Générateur/Correcteur de QCM papier - Nouveau")
        self.present()

    def _on_open(self, _btn) -> None:
        path = _file_dialog(self, "Ouvrir un projet", Gtk.FileChooserAction.OPEN,
                            filters=[("Projet JSON", ["*.json"])])
        if path is None:
            return
        try:
            self.project = project_mod.load_project(path)
            self.editor.project = self.project
            self.editor._fill_tree()
            self.editor._update_interval_label()

            # --- Synchroniser les champs d'info avec valeurs par défaut si vides ---
            def set_entry_with_default(entry, value, default, attr):
                """Applique une valeur par défaut et le style si vide."""
                if not value:
                    entry.set_text(default)
                    entry.get_style_context().add_class("suggestion")
                    setattr(self.project.settings, attr, default)
                else:
                    entry.set_text(value)
                    entry.get_style_context().remove_class("suggestion")

            # Ligne 1
            set_entry_with_default(self.entry_establishment, self.project.settings.establishment, "Université Lyon 1", "establishment")
            set_entry_with_default(self.entry_institute, self.project.settings.institute, "IUT LYON 1", "institute")
            set_entry_with_default(self.entry_formation, self.project.settings.formation, "Département GEii", "formation")

            # Ligne 2
            set_entry_with_default(self.entry_year, self.project.settings.year, "2026", "year")
            set_entry_with_default(self.entry_semester, self.project.settings.semester, "S1", "semester")
            set_entry_with_default(self.entry_teaching_unit, self.project.settings.teaching_unit, "UE3", "teaching_unit")

            # Ligne 3
            set_entry_with_default(self.entry_module_full, self.project.settings.module_full, "Mathématiques", "module_full")
            set_entry_with_default(self.entry_module_short, self.project.settings.module_short, "OML1", "module_short")

            # Ligne 4
            set_entry_with_default(self.entry_evaluation_full, self.project.settings.evaluation_full, "QCM Mathématiques", "evaluation_full")
            set_entry_with_default(self.entry_evaluation_short, self.project.settings.evaluation_short, "OML1", "evaluation_short")

            # Ligne 5
            set_entry_with_default(self.entry_teachers, self.project.settings.teachers, "BS", "teachers")
            set_entry_with_default(self.entry_date, self.project.settings.date, "09/10/2026", "date")
            set_entry_with_default(self.entry_duration, self.project.settings.duration, "1h", "duration")

            # Champs Génération
            self.entry_variants.set_text(self.project.settings.generate_variants)
            # affichage du nom du fichier dans la barre de titre
            self.set_title(f"Générateur/Correcteur de QCM papier - {os.path.basename(path)}")
            self.spin_students.set_value(max(1, min(1000, self.project.settings.generate_students)))  # Force la valeur dans [1, 1000]
            self.spin_count.set_value(max(1, min(4096, self.project.settings.generate_count)))      # Force la valeur dans [1, 4096]
            self.present()
            
            self.generate_status.set_text(f"Projet chargé : {path}")
        except Exception as e:
            self.generate_status.set_text(f"Erreur : {e}")
        
    def _on_save(self, _btn) -> None:
        """Enregistre le projet dans un fichier JSON."""
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
