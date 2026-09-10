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

Modifié pour inclure les paramètres de génération dans l'onglet Génération.
"""

from __future__ import annotations

import os

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib

from .. import generator, pdf_writer, project as project_mod, scanner, scodoc
from ..model import Project
from .editor import StructureEditor

def _file_dialog(parent, title: str, action, filters=None, initial_name=None):
    """Crée un sélecteur de fichier natif (GTK 4)."""
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


def _file_dialog_multiple(parent, title: str, filters=None):
    """Sélecteur de fichiers natif en mode sélection multiple (GTK 4)."""
    dialog = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.OPEN,
                                       None, None)
    dialog.set_select_multiple(True)
    if filters:
        for name, patterns in filters:
            filt = Gtk.FileFilter()
            filt.set_name(name)
            for p in patterns:
                filt.add_pattern(p)
            dialog.add_filter(filt)

    paths = []
    from gi.repository import GLib
    loop = GLib.MainLoop()

    def on_response(native, response):
        if response == Gtk.ResponseType.ACCEPT:
            files = dialog.get_files()
            for i in range(files.get_n_items()):
                file_obj = files.get_item(i)
                p = file_obj.get_path() if file_obj else None
                if p:
                    paths.append(p)
        dialog.destroy()
        loop.quit()

    dialog.connect("response", on_response)
    dialog.show()
    loop.run()
    return paths


def _img_to_texture(img) -> object:
    import io
    buf = io.BytesIO()
    img.save(buf, format="png")
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(buf.getvalue()))


class QcmWindow(Gtk.ApplicationWindow):
    """Fenêtre principale de l'application."""

    def __init__(self, **kwargs):
        super().__init__(title="Générateur/Correcteur de QCM papier",
                        default_width=1000, default_height=700, **kwargs)

        self.project = Project()

        # HeaderBar
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

        # Notebook
        self.notebook = Gtk.Notebook()
        self.set_child(self.notebook)

        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(b"""
            .suggestion {
                color: #666;
                font-style: italic;
            }
            .prog_ok {
                background-color: #4CAF50;
                color: white;
            }
            .prog_err {
                background-color: #F44336;
                color: white;
            }
            .prog_rest {
                background-color: #9E9E9E;
                color: white;
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
        self.notebook.set_current_page(1)

    # ------------------------------------------------------------------
    # Onglet Informations
    # ------------------------------------------------------------------
    def _build_info_tab(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # Ligne 1
        grid1 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid1.attach(Gtk.Label(label="Établissement :"), 0, 0, 1, 1)
        self.entry_establishment = Gtk.Entry()
        self.entry_establishment.set_hexpand(True)
        self.entry_establishment.set_text(self.project.settings.establishment or "Université Lyon 1")
        self.entry_establishment.connect("changed",
            lambda e: setattr(self.project.settings, "establishment", e.get_text()))
        if not self.project.settings.establishment:
            self.entry_establishment.get_style_context().add_class("suggestion")
        grid1.attach(self.entry_establishment, 1, 0, 1, 1)

        grid1.attach(Gtk.Label(label="Institut :"), 2, 0, 1, 1)
        self.entry_institute = Gtk.Entry()
        self.entry_institute.set_hexpand(True)
        self.entry_institute.set_text(self.project.settings.institute or "IUT LYON 1")
        self.entry_institute.connect("changed",
            lambda e: setattr(self.project.settings, "institute", e.get_text()))
        if not self.project.settings.institute:
            self.entry_institute.get_style_context().add_class("suggestion")
        grid1.attach(self.entry_institute, 3, 0, 1, 1)

        grid1.attach(Gtk.Label(label="Formation :"), 4, 0, 1, 1)
        self.entry_formation = Gtk.Entry()
        self.entry_formation.set_hexpand(True)
        self.entry_formation.set_text(self.project.settings.formation or "Département GEii")
        self.entry_formation.connect("changed",
            lambda e: setattr(self.project.settings, "formation", e.get_text()))
        if not self.project.settings.formation:
            self.entry_formation.get_style_context().add_class("suggestion")
        grid1.attach(self.entry_formation, 5, 0, 1, 1)
        box.append(grid1)

        # Ligne 2
        grid2 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid2.attach(Gtk.Label(label="Année :"), 0, 0, 1, 1)
        self.entry_year = Gtk.Entry()
        self.entry_year.set_hexpand(True)
        self.entry_year.set_text(self.project.settings.year or "2026")
        self.entry_year.connect("changed",
            lambda e: setattr(self.project.settings, "year", e.get_text()))
        if not self.project.settings.year:
            self.entry_year.get_style_context().add_class("suggestion")
        grid2.attach(self.entry_year, 1, 0, 1, 1)

        grid2.attach(Gtk.Label(label="Semestre :"), 2, 0, 1, 1)
        self.entry_semester = Gtk.Entry()
        self.entry_semester.set_hexpand(True)
        self.entry_semester.set_text(self.project.settings.semester or "S1")
        self.entry_semester.connect("changed",
            lambda e: setattr(self.project.settings, "semester", e.get_text()))
        if not self.project.settings.semester:
            self.entry_semester.get_style_context().add_class("suggestion")
        grid2.attach(self.entry_semester, 3, 0, 1, 1)

        grid2.attach(Gtk.Label(label="Unité d'enseignement :"), 4, 0, 1, 1)
        self.entry_teaching_unit = Gtk.Entry()
        self.entry_teaching_unit.set_hexpand(True)
        self.entry_teaching_unit.set_text(self.project.settings.teaching_unit or "UE3")
        self.entry_teaching_unit.connect("changed",
            lambda e: setattr(self.project.settings, "teaching_unit", e.get_text()))
        if not self.project.settings.teaching_unit:
            self.entry_teaching_unit.get_style_context().add_class("suggestion")
        grid2.attach(self.entry_teaching_unit, 5, 0, 1, 1)
        box.append(grid2)

        # Ligne 3
        grid3 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid3.attach(Gtk.Label(label="Module complet :"), 0, 0, 1, 1)
        self.entry_module_full = Gtk.Entry()
        self.entry_module_full.set_hexpand(True)
        self.entry_module_full.set_text(self.project.settings.module_full or "Mathématiques")
        self.entry_module_full.connect("changed",
            lambda e: setattr(self.project.settings, "module_full", e.get_text()))
        if not self.project.settings.module_full:
            self.entry_module_full.get_style_context().add_class("suggestion")
        grid3.attach(self.entry_module_full, 1, 0, 1, 1)

        grid3.attach(Gtk.Label(label="Module abrégé :"), 2, 0, 1, 1)
        self.entry_module_short = Gtk.Entry()
        self.entry_module_short.set_hexpand(True)
        self.entry_module_short.set_text(self.project.settings.module_short or "OML1")
        self.entry_module_short.connect("changed",
            lambda e: setattr(self.project.settings, "module_short", e.get_text()))
        if not self.project.settings.module_short:
            self.entry_module_short.get_style_context().add_class("suggestion")
        grid3.attach(self.entry_module_short, 3, 0, 1, 1)
        box.append(grid3)

        # Ligne 4
        grid4 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid4.attach(Gtk.Label(label="Évaluation complète :"), 0, 0, 1, 1)
        self.entry_evaluation_full = Gtk.Entry()
        self.entry_evaluation_full.set_hexpand(True)
        self.entry_evaluation_full.set_text(self.project.settings.evaluation_full or "QCM Mathématiques")
        self.entry_evaluation_full.connect("changed",
            lambda e: setattr(self.project.settings, "evaluation_full", e.get_text()))
        if not self.project.settings.evaluation_full:
            self.entry_evaluation_full.get_style_context().add_class("suggestion")
        grid4.attach(self.entry_evaluation_full, 1, 0, 1, 1)

        grid4.attach(Gtk.Label(label="Évaluation abrégée :"), 2, 0, 1, 1)
        self.entry_evaluation_short = Gtk.Entry()
        self.entry_evaluation_short.set_hexpand(True)
        self.entry_evaluation_short.set_text(self.project.settings.evaluation_short or "OML1")
        self.entry_evaluation_short.connect("changed",
            lambda e: setattr(self.project.settings, "evaluation_short", e.get_text()))
        if not self.project.settings.evaluation_short:
            self.entry_evaluation_short.get_style_context().add_class("suggestion")
        grid4.attach(self.entry_evaluation_short, 3, 0, 1, 1)
        box.append(grid4)

        # Ligne 5
        grid5 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid5.attach(Gtk.Label(label="Enseignants :"), 0, 0, 1, 1)
        self.entry_teachers = Gtk.Entry()
        self.entry_teachers.set_hexpand(True)
        self.entry_teachers.set_text(self.project.settings.teachers or "BS")
        self.entry_teachers.connect("changed",
            lambda e: setattr(self.project.settings, "teachers", e.get_text()))
        if not self.project.settings.teachers:
            self.entry_teachers.get_style_context().add_class("suggestion")
        grid5.attach(self.entry_teachers, 1, 0, 1, 1)

        grid5.attach(Gtk.Label(label="Date :"), 2, 0, 1, 1)
        self.entry_date = Gtk.Entry()
        self.entry_date.set_hexpand(True)
        self.entry_date.set_text(self.project.settings.date or "09/10/2026")
        self.entry_date.connect("changed",
            lambda e: setattr(self.project.settings, "date", e.get_text()))
        if not self.project.settings.date:
            self.entry_date.get_style_context().add_class("suggestion")
        grid5.attach(self.entry_date, 3, 0, 1, 1)

        grid5.attach(Gtk.Label(label="Durée :"), 4, 0, 1, 1)
        self.entry_duration = Gtk.Entry()
        self.entry_duration.set_hexpand(True)
        self.entry_duration.set_text(self.project.settings.duration or "1h")
        self.entry_duration.connect("changed",
            lambda e: setattr(self.project.settings, "duration", e.get_text()))
        if not self.project.settings.duration:
            self.entry_duration.get_style_context().add_class("suggestion")
        grid5.attach(self.entry_duration, 5, 0, 1, 1)
        box.append(grid5)

        # Ligne 6: Format de papier
        grid6 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid6.attach(Gtk.Label(label="Format de papier :"), 0, 0, 1, 1)
        self.paper_format_combo = Gtk.ComboBoxText()
        self.paper_format_combo.append_text("A3")
        self.paper_format_combo.append_text("A4")
        self.paper_format_combo.append_text("A5")
        self.paper_format_combo.set_active(1)  # A4 par défaut
        self.paper_format_combo.connect("changed", self._on_paper_format_changed)
        grid6.attach(self.paper_format_combo, 1, 0, 1, 1)

        grid6.attach(Gtk.Label(label="Orientation :"), 2, 0, 1, 1)
        self.paper_orientation_combo = Gtk.ComboBoxText()
        self.paper_orientation_combo.append_text("Portrait")
        self.paper_orientation_combo.append_text("Paysage")
        self.paper_orientation_combo.append_text("Les deux (Aléatoire)")
        self.paper_orientation_combo.set_active(2)  # Les deux par défaut
        self.paper_orientation_combo.connect("changed", self._on_paper_orientation_changed)
        grid6.attach(self.paper_orientation_combo, 3, 0, 1, 1)
        box.append(grid6)

        # Ligne 7: Marges
        grid7 = Gtk.Grid(column_spacing=8, row_spacing=4)
        
        # Marge haute
        grid7.attach(Gtk.Label(label="Marge haute :"), 3, 0, 1, 1)
        self.margin_top_spin = Gtk.SpinButton()
        self.margin_top_spin.set_range(5, 25)
        self.margin_top_spin.set_increments(1, 1)
        self.margin_top_spin.set_value(10)
        self.margin_top_spin.connect("value-changed", 
            lambda s: setattr(self.project.settings, "margin_top", str(int(s.get_value()))))
        grid7.attach(self.margin_top_spin, 4, 0, 1, 1)
        

        # Ligne 8: Marges gauche/droite
        grid7.attach(Gtk.Label(label="Marges en mm :    "), 0, 1, 1, 1)
        
        grid7.attach(Gtk.Label(label="Marge gauche"), 1, 1, 1, 1)
        self.margin_left_spin = Gtk.SpinButton()
        self.margin_left_spin.set_range(5, 25)
        self.margin_left_spin.set_increments(1, 1)
        self.margin_left_spin.set_value(10)
        self.margin_left_spin.connect("value-changed", 
            lambda s: setattr(self.project.settings, "margin_left", str(int(s.get_value()))))
        grid7.attach(self.margin_left_spin, 2, 1, 1, 1)
        
        grid7.attach(Gtk.Label(label="Marge droite"), 5, 1, 1, 1)
        self.margin_right_spin = Gtk.SpinButton()
        self.margin_right_spin.set_range(5, 25)
        self.margin_right_spin.set_increments(1, 1)
        self.margin_right_spin.set_value(10)
        self.margin_right_spin.connect("value-changed", 
            lambda s: setattr(self.project.settings, "margin_right", str(int(s.get_value()))))
        grid7.attach(self.margin_right_spin, 6, 1, 1, 1)
        

        # Ligne 9: Marge basse
        grid7.attach(Gtk.Label(label="Marge basse :"), 3, 3, 1, 1)
        self.margin_bottom_spin = Gtk.SpinButton()
        self.margin_bottom_spin.set_range(5, 25)
        self.margin_bottom_spin.set_increments(1, 1)
        self.margin_bottom_spin.set_value(10)
        self.margin_bottom_spin.connect("value-changed", 
            lambda s: setattr(self.project.settings, "margin_bottom", str(int(s.get_value()))))
        grid7.attach(self.margin_bottom_spin, 4, 3, 1, 1)
        
        box.append(grid7)

        self.notebook.append_page(box, Gtk.Label(label="Informations"))

    # ------------------------------------------------------------------
    # Onglet Structure
    # ------------------------------------------------------------------
    def _build_structure_tab(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        self.editor = StructureEditor(self.project, on_change=self._on_structure_changed)
        box.append(self.editor)
        self.notebook.append_page(box, Gtk.Label(label="Structure"))

    def _on_structure_changed(self) -> None:
        self.project.settings.modified = True

    def _on_paper_format_changed(self, combo) -> None:
        """Gère le changement de format de papier."""
        format_text = combo.get_active_text()
        self.project.settings.paper_a3 = False
        self.project.settings.paper_a4 = False
        self.project.settings.paper_a5 = False
        if format_text == "A3":
            self.project.settings.paper_a3 = True
        elif format_text == "A4":
            self.project.settings.paper_a4 = True
        elif format_text == "A5":
            self.project.settings.paper_a5 = True

    def _on_paper_orientation_changed(self, combo) -> None:
        """Gère le changement d'orientation du papier."""
        orientation_text = combo.get_active_text()
        self.project.settings.paper_portrait = False
        self.project.settings.paper_landscape = False
        self.project.settings.paper_both = False
        if orientation_text == "Portrait":
            self.project.settings.paper_portrait = True
        elif orientation_text == "Paysage":
            self.project.settings.paper_landscape = True
        elif orientation_text == "Les deux (Aléatoire)":
            self.project.settings.paper_both = True

    # ------------------------------------------------------------------
    # Onglet Génération
    # ------------------------------------------------------------------
    def _build_generate_tab(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # Paramètres de génération des variantes
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        self.spin_students = Gtk.SpinButton.new_with_range(1, 1000, 1)
        self.spin_students.set_value(self.project.settings.generate_students)
        self.spin_count = Gtk.SpinButton.new_with_range(1, 4096, 1)
        self.spin_count.set_value(self.project.settings.generate_count)
        self.entry_variants = Gtk.Entry()
        self.entry_variants.set_placeholder_text("Ids variantes (séparés par ;)")
        grid.attach(Gtk.Label(label="Nombre d'étudiants :"), 0, 0, 1, 1)
        grid.attach(self.spin_students, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Nombre de variantes :"), 2, 0, 1, 1)
        grid.attach(self.spin_count, 3, 0, 1, 1)
        grid.attach(Gtk.Label(label="Ids variantes :"), 4, 0, 1, 1)
        grid.attach(self.entry_variants, 5, 0, 3, 1)
        box.append(grid)

        # Boutons
        btn_generate = Gtk.Button(label="Générer les variantes")
        btn_generate.connect("clicked", self._on_generate_variants)
        grid.attach(btn_generate,1,1,2,1)

        btn_pdf = Gtk.Button(label="      Générer le PDF      ")
        btn_pdf.connect("clicked", self._on_generate_pdf)
        grid.attach(btn_pdf,4,1,3,1)

        self.generate_status = Gtk.Label(label="")
        box.append(self.generate_status)

        # --- NOUVEAU : Paramètres de génération ---
        # Séparateur
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.append(separator)

        # Frame principal
        params_frame = Gtk.Frame(label="Paramètres de génération")
        params_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        params_box1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        params_box2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        params_box.append(params_box1)
        params_box.append(params_box2)
        params_frame.set_child(params_box)  # GTK4: set_child au lieu de add
        box.append(params_frame)

        # ===== SENS DE LECTURE =====
        dir_frame = Gtk.Frame(label="Sens de lecture")
        dir_grid = Gtk.Grid(column_spacing=10, row_spacing=5)
        dir_frame.set_child(dir_grid)  # GTK4
        dir_frame.set_margin_start(8)
        dir_frame.set_margin_end(8)
        dir_frame.set_margin_top(8)
        dir_frame.set_margin_bottom(8)

        # Identification
        dir_grid.attach(Gtk.Label(label="Identification:"), 0, 0, 1, 1)
        self.ident_dir_combo = Gtk.ComboBoxText()
        self.ident_dir_combo.append_text("→ puis ↓")
        self.ident_dir_combo.append_text("↓ puis →")
        self.ident_dir_combo.append_text("Aléatoire")
        self.ident_dir_combo.set_active(0)
        dir_grid.attach(self.ident_dir_combo, 1, 0, 1, 1)

        # Exercices
        dir_grid.attach(Gtk.Label(label="Exercices:"), 0, 1, 1, 1)
        self.exercise_dir_combo = Gtk.ComboBoxText()
        self.exercise_dir_combo.append_text("→ puis ↓")
        self.exercise_dir_combo.append_text("↓ puis →")
        self.exercise_dir_combo.append_text("Aléatoire")
        self.exercise_dir_combo.set_active(0)
        dir_grid.attach(self.exercise_dir_combo, 1, 1, 1, 1)

        # Questions
        dir_grid.attach(Gtk.Label(label="Questions:"), 0, 2, 1, 1)
        self.question_dir_combo = Gtk.ComboBoxText()
        self.question_dir_combo.append_text("→ puis ↓")
        self.question_dir_combo.append_text("↓ puis →")
        self.question_dir_combo.append_text("Aléatoire")
        self.question_dir_combo.set_active(0)
        dir_grid.attach(self.question_dir_combo, 1, 2, 1, 1)

        # Choix
        dir_grid.attach(Gtk.Label(label="Choix:"), 0, 3, 1, 1)
        self.choice_dir_combo = Gtk.ComboBoxText()
        self.choice_dir_combo.append_text("→ puis ↓")
        self.choice_dir_combo.append_text("↓ puis →")
        self.choice_dir_combo.append_text("Aléatoire")
        self.choice_dir_combo.set_active(0)
        dir_grid.attach(self.choice_dir_combo, 1, 3, 1, 1)

        params_box1.append(dir_frame)

        # ===== AJOUTS FANTÔMES =====
        new_frame = Gtk.Frame(label="Les fantômes")
        new_grid = Gtk.Grid(column_spacing=10, row_spacing=5)
        new_frame.set_child(new_grid)  # GTK4
        new_frame.set_margin_start(8)
        new_frame.set_margin_end(8)
        new_frame.set_margin_top(8)
        new_frame.set_margin_bottom(8)

        # Exercices fantômes
        new_grid.attach(Gtk.Label(label="Exercices fantômes :"), 0, 0, 1, 1)
        self.exercise_new_combo = Gtk.ComboBoxText()
        self.exercise_new_combo.append_text("Jamais")
        self.exercise_new_combo.append_text("Toujours")
        self.exercise_new_combo.append_text("De temps en temps")
        self.exercise_new_combo.set_active(0)
        new_grid.attach(self.exercise_new_combo, 1, 0, 1, 1)

        # Paramètres détaillés pour exercices fantômes
        new_grid.attach(Gtk.Label(label="Ajout"), 0, 1, 1, 1)
        self.exercise_new_exercises_spin = Gtk.SpinButton()
        self.exercise_new_exercises_spin.set_range(1, 9)
        self.exercise_new_exercises_spin.set_increments(1, 1)
        self.exercise_new_exercises_spin.set_value(1)
        new_grid.attach(self.exercise_new_exercises_spin, 1, 1, 1, 1)
        new_grid.attach(Gtk.Label(label="de"), 2, 1, 1, 1)
        new_grid.attach(Gtk.Label(label="exercice(s) intitulé(s)"), 3, 1, 1, 1)
        self.exercise_new_exercises_name_entry = Gtk.Entry()
        self.exercise_new_exercises_name_entry.set_text("Ne pas remplir")
        new_grid.attach(self.exercise_new_exercises_name_entry, 4, 1, 1, 1)

        new_grid.attach(Gtk.Label(label="contenant"), 0, 2, 1, 1)
        self.exercise_new_questions_spin = Gtk.SpinButton()
        self.exercise_new_questions_spin.set_range(1, 9)
        self.exercise_new_questions_spin.set_increments(1, 1)
        self.exercise_new_questions_spin.set_value(1)
        new_grid.attach(self.exercise_new_questions_spin, 1, 2, 1, 1)
        new_grid.attach(Gtk.Label(label="question(s) intitulée(s)"), 2, 2, 2, 1)
        self.exercise_new_questions_name_entry = Gtk.Entry()
        self.exercise_new_questions_name_entry.set_text("Inutilisé")
        new_grid.attach(self.exercise_new_questions_name_entry, 4, 2, 1, 1)

        new_grid.attach(Gtk.Label(label="contenant"), 0, 3, 1, 1)
        self.exercise_new_choices_spin = Gtk.SpinButton()
        self.exercise_new_choices_spin.set_range(1, 9)
        self.exercise_new_choices_spin.set_increments(1, 1)
        self.exercise_new_choices_spin.set_value(1)
        new_grid.attach(self.exercise_new_choices_spin, 1, 3, 1, 1)
        new_grid.attach(Gtk.Label(label="choix intitulé(s)"), 2, 3, 2, 1)
        self.exercise_new_choices_name_entry = Gtk.Entry()
        self.exercise_new_choices_name_entry.set_text("X")
        new_grid.attach(self.exercise_new_choices_name_entry, 4, 3, 1, 1)

        new_grid.attach(Gtk.Label(label="-----------------------------------"), 0, 4, 4, 1)
        # Questions fantômes
        new_grid.attach(Gtk.Label(label="Questions fantômes :"), 0, 5, 1, 1)
        self.question_new_combo = Gtk.ComboBoxText()
        self.question_new_combo.append_text("Jamais")
        self.question_new_combo.append_text("Toujours")
        self.question_new_combo.append_text("De temps en temps")
        self.question_new_combo.set_active(0)
        new_grid.attach(self.question_new_combo, 1, 5, 1, 1)

        # Paramètres détaillés pour questions fantômes
        new_grid.attach(Gtk.Label(label="Ajout"), 0, 6, 1, 1)
        self.question_new_questions_spin = Gtk.SpinButton()
        self.question_new_questions_spin.set_range(1, 9)
        self.question_new_questions_spin.set_increments(1, 1)
        self.question_new_questions_spin.set_value(1)
        new_grid.attach(self.question_new_questions_spin, 1, 6, 1, 1)
        new_grid.attach(Gtk.Label(label="question(s) intitulée(s)"), 2, 6, 2, 1)
        self.question_new_questions_name_entry = Gtk.Entry()
        self.question_new_questions_name_entry.set_text("Question")
        new_grid.attach(self.question_new_questions_name_entry, 4, 6, 1, 1)

        new_grid.attach(Gtk.Label(label="contenant"), 0, 7, 1, 1)
        self.question_new_choices_spin = Gtk.SpinButton()
        self.question_new_choices_spin.set_range(1, 9)
        self.question_new_choices_spin.set_increments(1, 1)
        self.question_new_choices_spin.set_value(4)
        new_grid.attach(self.question_new_choices_spin, 1, 7, 1, 1)
        new_grid.attach(Gtk.Label(label="choix intitulé(s)"), 2, 7, 2, 1)
        self.question_new_choices_name_entry = Gtk.Entry()
        self.question_new_choices_name_entry.set_text("X")
        new_grid.attach(self.question_new_choices_name_entry, 4, 7, 1, 1)

        new_grid.attach(Gtk.Label(label="------------------------------------"), 0, 8, 4, 1)

        # Choix fantômes
        new_grid.attach(Gtk.Label(label="Choix fantômes:"), 0, 9, 1, 1)
        self.choice_new_combo = Gtk.ComboBoxText()
        self.choice_new_combo.append_text("Jamais")
        self.choice_new_combo.append_text("Toujours")
        self.choice_new_combo.append_text("De temps en temps")
        self.choice_new_combo.set_active(0)
        new_grid.attach(self.choice_new_combo, 1, 9, 1, 1)

        # Paramètres détaillés pour choix fantômes
        new_grid.attach(Gtk.Label(label="Ajout"), 0, 10, 1, 1)
        self.choice_new_choices_spin = Gtk.SpinButton()
        self.choice_new_choices_spin.set_range(1, 9)
        self.choice_new_choices_spin.set_increments(1, 1)
        self.choice_new_choices_spin.set_value(1)
        new_grid.attach(self.choice_new_choices_spin, 1, 10, 1, 1)
        new_grid.attach(Gtk.Label(label="choix intitulé(s)"), 2, 10, 2, 1)
        self.choice_new_choices_name_entry = Gtk.Entry()
        self.choice_new_choices_name_entry.set_text("X")
        new_grid.attach(self.choice_new_choices_name_entry, 4, 10, 1, 1)
        # Choix fantômes précochés
        new_grid.attach(Gtk.Label(label="Choix fantômes précochés:"), 0, 11, 1, 1)
        self.checked_combo = Gtk.ComboBoxText()
        self.checked_combo.append_text("Jamais")
        self.checked_combo.append_text("Toujours")
        self.checked_combo.append_text("De temps en temps")
        self.checked_combo.set_active(0)
        new_grid.attach(self.checked_combo, 1,11, 1, 1)


        params_box2.append(new_frame)

        # ===== AUTRES OPTIONS =====
        other_frame = Gtk.Frame(label="Autres options")
        other_grid = Gtk.Grid(column_spacing=10, row_spacing=5)
        other_frame.set_child(other_grid)  # GTK4
        other_frame.set_margin_start(8)
        other_frame.set_margin_end(8)
        other_frame.set_margin_top(8)
        other_frame.set_margin_bottom(8)

        # Choix "seconde chance"
        other_grid.attach(Gtk.Label(label="Choix 'seconde chance':"), 0, 0, 1, 1)
        self.joker_check = Gtk.CheckButton()
        other_grid.attach(self.joker_check, 1, 0, 1, 1)

        params_box1.append(other_frame)

        # ===== ORDRE ALÉATOIRE =====
        order_frame = Gtk.Frame(label="Ordre aléatoire")
        order_grid = Gtk.Grid(column_spacing=10, row_spacing=5)
        order_frame.set_child(order_grid)  # GTK4
        order_frame.set_margin_start(8)
        order_frame.set_margin_end(8)
        order_frame.set_margin_top(8)
        order_frame.set_margin_bottom(8)

        # Exercices
        order_grid.attach(Gtk.Label(label="Ordre des exercices:"), 0, 0, 1, 1)
        self.exercise_order_combo = Gtk.ComboBoxText()
        self.exercise_order_combo.append_text("Jamais")
        self.exercise_order_combo.append_text("Toujours")
        self.exercise_order_combo.append_text("De temps en temps")
        self.exercise_order_combo.set_active(0)
        order_grid.attach(self.exercise_order_combo, 1, 0, 1, 1)

        # Questions
        order_grid.attach(Gtk.Label(label="Ordre des questions:"), 0, 1, 1, 1)
        self.question_order_combo = Gtk.ComboBoxText()
        self.question_order_combo.append_text("Jamais")
        self.question_order_combo.append_text("Toujours")
        self.question_order_combo.append_text("De temps en temps")
        self.question_order_combo.set_active(0)
        order_grid.attach(self.question_order_combo, 1, 1, 1, 1)

        # Choix
        order_grid.attach(Gtk.Label(label="Ordre des choix:"), 0, 2, 1, 1)
        self.choice_order_combo = Gtk.ComboBoxText()
        self.choice_order_combo.append_text("Jamais")
        self.choice_order_combo.append_text("Toujours")
        self.choice_order_combo.append_text("De temps en temps")
        self.choice_order_combo.set_active(0)
        order_grid.attach(self.choice_order_combo, 1, 2, 1, 1)

        params_box1.append(order_frame)

        # Charger les paramètres actuels
        self._load_generation_params()

        self.notebook.append_page(box, Gtk.Label(label="Génération"))

    def _load_generation_params(self):
        """Charge les paramètres de génération dans les widgets."""
        settings = self.project.settings

        # ===== SENS DE LECTURE =====
        dir_groups = [
            ("identification_dir", self.ident_dir_combo, "identification_dir_left", "identification_dir_top", "identification_dir_both"),
            ("exercise_dir", self.exercise_dir_combo, "exercise_dir_left", "exercise_dir_top", "exercise_dir_both"),
            ("question_dir", self.question_dir_combo, "question_dir_left", "question_dir_top", "question_dir_both"),
            ("choice_dir", self.choice_dir_combo, "choice_dir_left", "choice_dir_top", "choice_dir_both")
        ]
        for group, combo, left_attr, top_attr, both_attr in dir_groups:
            # Vérifier que TOUS les attributs existent
            for attr in (left_attr, top_attr, both_attr):
                if not hasattr(settings, attr):
                    raise AttributeError(
                        f"Attribut manquant dans ProjectSettings : '{attr}'. "
                        f"Vérifiez que le fichier JSON ou le modèle est complet."
                    )

            # Accès direct (sans getattr)
            left_val = getattr(settings, left_attr)
            top_val = getattr(settings, top_attr)
            both_val = getattr(settings, both_attr)

            if both_val:
                combo.set_active(2)  # Aléatoire
            elif top_val:
                combo.set_active(1)  # ↓ puis →
            elif left_val:
                combo.set_active(0)  # → puis ↓
            else:
                combo.set_active(0)  # Par défaut

        # ===== AJOUTS FANTÔMES =====
        new_groups = [
            ("exercise_new", self.exercise_new_combo, "exercise_new_never", "exercise_new_always", "exercise_new_sometimes"),
            ("question_new", self.question_new_combo, "question_new_never", "question_new_always", "question_new_sometimes"),
            ("choice_new", self.choice_new_combo, "choice_new_never", "choice_new_always", "choice_new_sometimes")
        ]
        for group, combo, never_attr, always_attr, sometimes_attr in new_groups:
            for attr in (never_attr, always_attr, sometimes_attr):
                if not hasattr(settings, attr):
                    raise AttributeError(
                        f"Attribut manquant dans ProjectSettings : '{attr}'. "
                        f"Vérifiez que le fichier JSON ou le modèle est complet."
                    )
            never_val = getattr(settings, never_attr)
            always_val = getattr(settings, always_attr)
            sometimes_val = getattr(settings, sometimes_attr)

            if sometimes_val:
                combo.set_active(2)  # De temps en temps
            elif always_val:
                combo.set_active(1)  # Toujours
            elif never_val:
                combo.set_active(0)  # Jamais
            else:
                combo.set_active(0)  # Par défaut

        # Charger les paramètres détaillés pour les ajouts fantômes
        self.exercise_new_exercises_spin.set_value(settings.exercise_new_exercises)
        self.exercise_new_exercises_name_entry.set_text(settings.exercise_new_exercises_name)
        self.exercise_new_questions_spin.set_value(settings.exercise_new_questions)
        self.exercise_new_questions_name_entry.set_text(settings.exercise_new_questions_name)
        self.exercise_new_choices_spin.set_value(settings.exercise_new_choices)
        self.exercise_new_choices_name_entry.set_text(settings.exercise_new_choices_name)
        
        self.question_new_questions_spin.set_value(settings.question_new_questions)
        self.question_new_questions_name_entry.set_text(settings.question_new_questions_name)
        self.question_new_choices_spin.set_value(settings.question_new_choices)
        self.question_new_choices_name_entry.set_text(settings.question_new_choices_name)
        
        self.choice_new_choices_spin.set_value(settings.choice_new_choices)
        self.choice_new_choices_name_entry.set_text(settings.choice_new_choices_name)

        # ===== FORMAT DE PAPIER =====
        # Format
        if settings.paper_a3:
            self.paper_format_combo.set_active(0)
        elif settings.paper_a4:
            self.paper_format_combo.set_active(1)
        elif settings.paper_a5:
            self.paper_format_combo.set_active(2)
        
        # Orientation
        if settings.paper_both:
            self.paper_orientation_combo.set_active(2)
        elif settings.paper_landscape:
            self.paper_orientation_combo.set_active(1)
        elif settings.paper_portrait:
            self.paper_orientation_combo.set_active(0)

        # ===== MARGE =====
        self.margin_top_spin.set_value(int(settings.margin_top or 10))
        self.margin_left_spin.set_value(int(settings.margin_left or 10))
        self.margin_right_spin.set_value(int(settings.margin_right or 10))
        self.margin_bottom_spin.set_value(int(settings.margin_bottom or 10))

        # ===== AUTRES OPTIONS =====
        if not hasattr(settings, "choice_joker_always"):
            raise AttributeError("Attribut manquant dans ProjectSettings : 'choice_joker_always'.")
        self.joker_check.set_active(settings.choice_joker_always)

        # Choix fantômes précochés
        for attr in ("choice_checked_never", "choice_checked_always", "choice_checked_sometimes"):
            if not hasattr(settings, attr):
                raise AttributeError(f"Attribut manquant dans ProjectSettings : '{attr}'.")
        checked_never = settings.choice_checked_never
        checked_always = settings.choice_checked_always
        checked_sometimes = settings.choice_checked_sometimes
        if checked_sometimes:
            self.checked_combo.set_active(2)
        elif checked_always:
            self.checked_combo.set_active(1)
        elif checked_never:
            self.checked_combo.set_active(0)
        else:
            self.checked_combo.set_active(0)

        # ===== ORDRE ALÉATOIRE =====
        order_groups = [
            ("exercise_order", self.exercise_order_combo, "exercise_order_never", "exercise_order_always", "exercise_order_sometimes"),
            ("question_order", self.question_order_combo, "question_order_never", "question_order_always", "question_order_sometimes"),
            ("choice_order", self.choice_order_combo, "choice_order_never", "choice_order_always", "choice_order_sometimes")
        ]
        for group, combo, never_attr, always_attr, sometimes_attr in order_groups:
            for attr in (never_attr, always_attr, sometimes_attr):
                if not hasattr(settings, attr):
                    raise AttributeError(
                        f"Attribut manquant dans ProjectSettings : '{attr}'. "
                        f"Vérifiez que le fichier JSON ou le modèle est complet."
                    )
            never_val = getattr(settings, never_attr)
            always_val = getattr(settings, always_attr)
            sometimes_val = getattr(settings, sometimes_attr)

            if sometimes_val:
                combo.set_active(2)
            elif always_val:
                combo.set_active(1)
            elif never_val:
                combo.set_active(0)
            else:
                combo.set_active(0)
            
    def _save_generation_params(self):
        """Sauvegarde les paramètres des widgets dans ProjectSettings."""
        settings = self.project.settings

        # ===== SENS DE LECTURE =====
        dir_groups = [
            ("identification_dir", self.ident_dir_combo, "identification_dir_left", "identification_dir_top", "identification_dir_both"),
            ("exercise_dir", self.exercise_dir_combo, "exercise_dir_left", "exercise_dir_top", "exercise_dir_both"),
            ("question_dir", self.question_dir_combo, "question_dir_left", "question_dir_top", "question_dir_both"),
            ("choice_dir", self.choice_dir_combo, "choice_dir_left", "choice_dir_top", "choice_dir_both")
        ]
        for group, combo, left_attr, top_attr, both_attr in dir_groups:
            active = combo.get_active()
            # Réinitialiser tous les booléens à False
            setattr(settings, left_attr, False)
            setattr(settings, top_attr, False)
            setattr(settings, both_attr, False)
            # Activer le bon booléen
            if active == 2:  # Aléatoire
                setattr(settings, both_attr, True)
            elif active == 1:  # ↓ puis →
                setattr(settings, top_attr, True)
            else:  # 0: → puis ↓
                setattr(settings, left_attr, True)

        # ===== AJOUTS FANTÔMES =====
        new_groups = [
            ("exercise_new", self.exercise_new_combo, "exercise_new_never", "exercise_new_always", "exercise_new_sometimes"),
            ("question_new", self.question_new_combo, "question_new_never", "question_new_always", "question_new_sometimes"),
            ("choice_new", self.choice_new_combo, "choice_new_never", "choice_new_always", "choice_new_sometimes")
        ]
        for group, combo, never_attr, always_attr, sometimes_attr in new_groups:
            active = combo.get_active()
            setattr(settings, never_attr, False)
            setattr(settings, always_attr, False)
            setattr(settings, sometimes_attr, False)
            if active == 2:  # De temps en temps
                setattr(settings, sometimes_attr, True)
            elif active == 1:  # Toujours
                setattr(settings, always_attr, True)
            else:  # 0: Jamais
                setattr(settings, never_attr, True)

        # Sauvegarder les paramètres détaillés pour les ajouts fantômes
        settings.exercise_new_exercises = self.exercise_new_exercises_spin.get_value_as_int()
        settings.exercise_new_exercises_name = self.exercise_new_exercises_name_entry.get_text()
        settings.exercise_new_questions = self.exercise_new_questions_spin.get_value_as_int()
        settings.exercise_new_questions_name = self.exercise_new_questions_name_entry.get_text()
        settings.exercise_new_choices = self.exercise_new_choices_spin.get_value_as_int()
        settings.exercise_new_choices_name = self.exercise_new_choices_name_entry.get_text()
        
        settings.question_new_questions = self.question_new_questions_spin.get_value_as_int()
        settings.question_new_questions_name = self.question_new_questions_name_entry.get_text()
        settings.question_new_choices = self.question_new_choices_spin.get_value_as_int()
        settings.question_new_choices_name = self.question_new_choices_name_entry.get_text()
        
        settings.choice_new_choices = self.choice_new_choices_spin.get_value_as_int()
        settings.choice_new_choices_name = self.choice_new_choices_name_entry.get_text()

        # ===== FORMAT DE PAPIER =====
        # Format
        format_active = self.paper_format_combo.get_active()
        settings.paper_a3 = (format_active == 0)
        settings.paper_a4 = (format_active == 1)
        settings.paper_a5 = (format_active == 2)
        
        # Orientation
        orientation_active = self.paper_orientation_combo.get_active()
        settings.paper_portrait = (orientation_active == 0)
        settings.paper_landscape = (orientation_active == 1)
        settings.paper_both = (orientation_active == 2)

        # ===== MARGE =====
        settings.margin_top = str(int(self.margin_top_spin.get_value()))
        settings.margin_left = str(int(self.margin_left_spin.get_value()))
        settings.margin_right = str(int(self.margin_right_spin.get_value()))
        settings.margin_bottom = str(int(self.margin_bottom_spin.get_value()))

        # ===== AUTRES OPTIONS =====
        settings.choice_joker_always = self.joker_check.get_active()

        # Choix fantômes précochés
        active = self.checked_combo.get_active()
        settings.choice_checked_never = False
        settings.choice_checked_always = False
        settings.choice_checked_sometimes = False
        if active == 2:
            settings.choice_checked_sometimes = True
        elif active == 1:
            settings.choice_checked_always = True
        else:
            settings.choice_checked_never = True

        # ===== ORDRE ALÉATOIRE =====
        order_groups = [
            ("exercise_order", self.exercise_order_combo, "exercise_order_never", "exercise_order_always", "exercise_order_sometimes"),
            ("question_order", self.question_order_combo, "question_order_never", "question_order_always", "question_order_sometimes"),
            ("choice_order", self.choice_order_combo, "choice_order_never", "choice_order_always", "choice_order_sometimes")
        ]
        for group, combo, never_attr, always_attr, sometimes_attr in order_groups:
            active = combo.get_active()
            setattr(settings, never_attr, False)
            setattr(settings, always_attr, False)
            setattr(settings, sometimes_attr, False)
            if active == 2:
                setattr(settings, sometimes_attr, True)
            elif active == 1:
                setattr(settings, always_attr, True)
            else:
                setattr(settings, never_attr, True)

    def _on_generate_variants(self, _btn) -> None:
        self._save_generation_params()  # Sauvegarder les paramètres avant de générer
        self.project.settings.generate_students = int(self.spin_students.get_value())
        self.project.settings.generate_count = int(self.spin_count.get_value())
        self.project.settings.generate_variants = self.entry_variants.get_text()

        success, failed = generator.generate_all(self.project, retry=True)

        # Stocker TOUS les IDs (succès + échecs + remplacements)
        all_ids = success + failed
        self.entry_variants.set_text(";".join(str(i) for i in all_ids))

        # Message
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
                            initial_name=f"{name}.pdf",
                            filters=[("Fichiers PDF", ["*.pdf"])])
        # Forcer l'extension .pdf si absente
        if path and not path.endswith('.pdf'):
            path += '.pdf'
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

        # Chargement des copies
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

        clair_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        clair_box.append(Gtk.Label(label="Seuil de détection :"))
        self.clair_spin = Gtk.SpinButton.new_with_range(50, 255, 5)
        self.clair_spin.set_value(140)
        clair_box.append(self.clair_spin)
        clair_box.append(Gtk.Label(label="(↑ pour scans plus sombres)"))
        box.append(clair_box)

        self.copies: list[str] = []
        self.copies_list = Gtk.ListBox()
        self.copies_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.copy_rows: dict[str, dict] = {}
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_child(self.copies_list)
        box.append(scroll)

        self.marking_status = Gtk.Label(label="")
        box.append(self.marking_status)

        # Résultats
        self.results_store = Gtk.ListStore(str, str, str, str, str)
        results_tree = Gtk.TreeView(model=self.results_store)
        for i, title in enumerate(["Fichier", "Variante", "Étudiant", "Note", "Statut"]):
            results_tree.append_column(
                Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i))
        scroll2 = Gtk.ScrolledWindow()
        scroll2.set_vexpand(True)
        scroll2.set_child(results_tree)
        box.append(scroll2)

        # Affichage des pages corrigées
        view_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.page_selector = Gtk.DropDown.new_from_strings([""])
        self.page_selector.connect("notify::selected", self._on_page_selected)
        view_box.append(self.page_selector)
        btn_prev = Gtk.Button(label="Précédent")
        btn_prev.connect("clicked", lambda _b: self._show_marked_page(-1))
        btn_next = Gtk.Button(label="Suivant")
        btn_next.connect("clicked", lambda _b: self._show_marked_page(+1))
        btn_enlarge = Gtk.Button(label="Agrandir")
        btn_enlarge.connect("clicked", self._on_enlarge_page)
        view_box.append(btn_prev)
        view_box.append(btn_next)
        view_box.append(btn_enlarge)
        box.append(view_box)

        self.marked_pages: list = []
        self.marked_image = Gtk.Picture()
        scroll3 = Gtk.ScrolledWindow()
        scroll3.set_vexpand(True)
        scroll3.set_hexpand(True)
        scroll3.set_child(self.marked_image)
        box.append(scroll3)

        self.notebook.append_page(box, Gtk.Label(label="Correction"))

    def _add_copy_row(self, path: str) -> None:
        fname = os.path.basename(path)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_start(4)
        row.set_margin_end(4)
        row.set_margin_top(2)
        row.set_margin_bottom(2)
        lbl = Gtk.Label(label=fname)
        lbl.set_xalign(0)
        lbl.set_hexpand(True)
        row.append(lbl)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar.set_size_request(120, 20)
        lbl_ok = Gtk.Label(label="")
        lbl_err = Gtk.Label(label="")
        lbl_rest = Gtk.Label(label="")
        for l, css in [(lbl_ok, "prog_ok"), (lbl_err, "prog_err"),
                        (lbl_rest, "prog_rest")]:
            l.get_style_context().add_class(css)
            bar.append(l)
        row.append(bar)
        self.copies_list.append(row)
        self.copy_rows[path] = {
            "row": row, "bar": bar,
            "lbl_ok": lbl_ok, "lbl_err": lbl_err, "lbl_rest": lbl_rest,
            "n_ok": 0, "n_err": 0, "n_pages": 0,
        }

    def _on_load_copies(self, _btn) -> None:
        paths = _file_dialog_multiple(self, "Choisir les copies",
                            filters=[("PDF et images", ["*.pdf", "*.png",
                                                         "*.jpg", "*.jpeg"])])
        if not paths:
            return
        for p in paths:
            if p not in self.copies:
                self.copies.append(p)
                self._add_copy_row(p)
        self.marking_status.set_text(f"{len(self.copies)} copie(s) chargée(s).")

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
        self.marked_pages = []
        notes: dict[str, float] = {}
        n_ok = 0
        n_err = 0
        total = len(self.copies)
        for copy_path in self.copies:
            fname = os.path.basename(copy_path)
            info = self.copy_rows.get(copy_path)
            try:
                pages = scanner.load_pages_from_file(copy_path, dpi=150)
            except Exception as e:
                n_err += 1
                self.results_store.append([fname, "",
                                            "", "", f"Erreur : {e}"])
                if info:
                    info["n_err"] = 1
                    info["n_pages"] = 1
                    self._update_copy_row(copy_path)
                continue
            if info:
                info["n_pages"] = len(pages)
            for page in pages:
                ok = scanner.auto_check(page, self.project,
                                         clair=int(self.clair_spin.get_value()))
                if ok:
                    n_ok += 1
                    if info:
                        info["n_ok"] += 1
                    eid = page.student_eid or page.student_id or ""
                    note = page.value if page.value is not None else 0.0
                    if eid:
                        notes[eid] = note
                    self.results_store.append([
                        fname,
                        str(page.variant_id or ""),
                        page.student_id or "",
                        f"{note:.2f}",
                        "complète" if page.complete else "incomplète",
                    ])
                    label = f"{fname} v{page.variant_id} {page.student_id or ''}"
                    self.marked_pages.append((label, page))
                else:
                    n_err += 1
                    if info:
                        info["n_err"] += 1
                    reason = "Échec alignement"
                    if page.variant_id is None:
                        reason = "Code-barres non trouvé"
                    elif page.student_id is None:
                        reason = "N° étudiant non trouvé"
                    self.results_store.append([fname, "",
                                                "", "", reason])
                    label = f"{fname} ⚠ {reason}"
                    self.marked_pages.append((label, page))
                if info:
                    self._update_copy_row(copy_path)
        self._last_notes = notes
        self.marking_status.set_text(
            f"{n_ok} corrigée(s), {n_err} en erreur sur {total}.")
        self._refresh_page_selector()

    def _update_copy_row(self, copy_path: str) -> None:
        info = self.copy_rows.get(copy_path)
        if info is None:
            return
        n_ok = info["n_ok"]
        n_err = info["n_err"]
        n_total = info["n_pages"]
        n_rest = max(0, n_total - n_ok - n_err)
        total = n_ok + n_err + n_rest
        info["lbl_ok"].set_text(str(n_ok) if n_ok else "")
        info["lbl_err"].set_text(str(n_err) if n_err else "")
        info["lbl_rest"].set_text(str(n_rest) if n_rest else "")
        bar_w = 120
        if total > 0:
            info["lbl_ok"].set_size_request(max(bar_w * n_ok // total, 14 if n_ok else 0), -1)
            info["lbl_err"].set_size_request(max(bar_w * n_err // total, 14 if n_err else 0), -1)
            info["lbl_rest"].set_size_request(max(bar_w * n_rest // total, 14 if n_rest else 0), -1)
        else:
            info["lbl_ok"].set_size_request(0, -1)
            info["lbl_err"].set_size_request(0, -1)
            info["lbl_rest"].set_size_request(bar_w, -1)
        ctx = GLib.MainContext.default()
        while ctx.pending():
            ctx.iteration(False)
        ctx.iteration(False)

    def _refresh_page_selector(self) -> None:
        labels = [lbl for lbl, _p in self.marked_pages] or [""]
        sm = Gtk.StringList.new(labels)
        self.page_selector.set_model(sm)
        if self.marked_pages:
            self._display_marked_page(0)

    def _on_page_selected(self, _dropdown, _pspec) -> None:
        idx = self.page_selector.get_selected()
        if idx >= 0 and idx < len(self.marked_pages):
            self._display_marked_page(idx)

    def _show_marked_page(self, delta: int) -> None:
        if not self.marked_pages:
            return
        idx = self.page_selector.get_selected()
        idx = max(0, min(len(self.marked_pages) - 1, idx + delta))
        self.page_selector.set_selected(idx)
        self._display_marked_page(idx)

    def _display_marked_page(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.marked_pages):
            return
        _label, page = self.marked_pages[idx]
        img = scanner.render_marked_page(page)
        if img is None:
            return
        from PIL import Image as PILImage
        max_w = max(200, self.get_width() - 40)
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), PILImage.LANCZOS)
        self.marked_image.set_paintable(_img_to_texture(img))

    def _on_enlarge_page(self, _btn) -> None:
        idx = self.page_selector.get_selected()
        if idx < 0 or idx >= len(self.marked_pages):
            return
        win = MarkedPageWindow(self.marked_pages, idx, self,
                               on_navigate=self._enlarge_navigate,
                               project=self.project)
        win.present()

    def _enlarge_navigate(self, idx: int) -> None:
        if 0 <= idx < len(self.marked_pages):
            self.page_selector.set_selected(idx)


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
    # Menu
    # ------------------------------------------------------------------
    def _on_new(self, _btn) -> None:
        self.project = Project()
        self.editor.project = self.project
        self.editor._fill_tree()
        self.copies = []
        while self.copies_list.get_first_child() is not None:
            self.copies_list.remove(self.copies_list.get_first_child())
        self.copy_rows.clear()
        self.results_store.clear()
        self.generate_status.set_text("Nouveau projet.")
        self.set_title("Générateur/Correcteur de QCM papier - Nouveau")
        self.present()

    def _on_open(self, _btn) -> None:
        path = _file_dialog(self, "Ouvrir un projet", Gtk.FileChooserAction.OPEN,
                            filters=[("Projet JSON", ["*.json"])])
        if path is None:
            return
        self._load_project_from_path(path)

    def _load_project_from_path(self, path: str) -> None:
        """Charge un projet depuis un fichier JSON et rafraîchit l'interface."""
        try:
            self.project = project_mod.load_project(path)
            self.editor.project = self.project
            self.editor._fill_tree()
            self.editor._update_interval_label()

            def set_entry_with_default(entry, value, default, attr):
                if not value:
                    entry.set_text(default)
                    entry.get_style_context().add_class("suggestion")
                    setattr(self.project.settings, attr, default)
                else:
                    entry.set_text(value)
                    entry.get_style_context().remove_class("suggestion")

            set_entry_with_default(self.entry_establishment, self.project.settings.establishment, "Université Lyon 1", "establishment")
            set_entry_with_default(self.entry_institute, self.project.settings.institute, "IUT LYON 1", "institute")
            set_entry_with_default(self.entry_formation, self.project.settings.formation, "Département GEii", "formation")
            set_entry_with_default(self.entry_year, self.project.settings.year, "2026", "year")
            set_entry_with_default(self.entry_semester, self.project.settings.semester, "S1", "semester")
            set_entry_with_default(self.entry_teaching_unit, self.project.settings.teaching_unit, "UE3", "teaching_unit")
            set_entry_with_default(self.entry_module_full, self.project.settings.module_full, "Mathématiques", "module_full")
            set_entry_with_default(self.entry_module_short, self.project.settings.module_short, "OML1", "module_short")
            set_entry_with_default(self.entry_evaluation_full, self.project.settings.evaluation_full, "QCM Mathématiques", "evaluation_full")
            set_entry_with_default(self.entry_evaluation_short, self.project.settings.evaluation_short, "OML1", "evaluation_short")
            set_entry_with_default(self.entry_teachers, self.project.settings.teachers, "BS", "teachers")
            set_entry_with_default(self.entry_date, self.project.settings.date, "09/10/2026", "date")
            set_entry_with_default(self.entry_duration, self.project.settings.duration, "1h", "duration")

            self.entry_variants.set_text(self.project.settings.generate_variants)
            self.spin_students.set_value(max(1, min(1000, self.project.settings.generate_students)))
            self.spin_count.set_value(max(1, min(4096, self.project.settings.generate_count)))

            # Charger les paramètres de génération
            self._load_generation_params()

            self.set_title(f"Générateur/Correcteur de QCM papier - {os.path.basename(path)}")
            self.generate_status.set_text(f"Projet chargé : {path}")            

        except Exception as e:
            self.generate_status.set_text(f"Erreur : {e}")

    def _on_save(self, _btn) -> None:
        """Enregistre le projet dans un fichier JSON."""
        self._save_generation_params()  # Sauvegarder les paramètres avant d'enregistrer
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


class MarkedPageWindow(Gtk.Window):
    """Fenêtre pop-up affichant une page corrigée en grand avec zoom et menu latéral."""

    def __init__(self, marked_pages, idx, parent=None, on_navigate=None,
                 project=None):
        super().__init__(title="Page corrigée", transient_for=parent,
                         default_width=1100, default_height=800,
                         modal=False, destroy_with_parent=True)
        self.pages = marked_pages
        self.idx = idx
        self.on_navigate = on_navigate
        self._project = project
        self._zoom = 1.0
        self._img = None

        main = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.set_child(main)

        # Zone d'affichage : ScrolledWindow + Image
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left.set_hexpand(True)
        left.set_vexpand(True)
        main.append(left)

        # Barre de zoom
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        zoom_box.set_margin_start(6)
        zoom_box.set_margin_end(6)
        zoom_box.set_margin_top(6)
        zoom_box.set_margin_bottom(6)
        btn_out = Gtk.Button(label="−")
        btn_out.connect("clicked", lambda _b: self._set_zoom(self._zoom - 0.25))
        self.zoom_label = Gtk.Label(label="100 %")
        btn_in = Gtk.Button(label="+")
        btn_in.connect("clicked", lambda _b: self._set_zoom(self._zoom + 0.25))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.25, 4.0, 0.25)
        scale.set_value(1.0)
        scale.set_hexpand(True)
        scale.connect("value-changed", lambda s: self._set_zoom(s.get_value(), from_scale=True))
        self.zoom_scale = scale
        zoom_box.append(btn_out)
        zoom_box.append(btn_in)
        zoom_box.append(scale)
        zoom_box.append(self.zoom_label)
        left.append(zoom_box)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_hexpand(True)
        self.scroll.set_vexpand(True)
        self.image = Gtk.Picture()
        self.scroll.set_child(self.image)
        left.append(self.scroll)

        scroll_ctrl = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll_ctrl.connect("scroll", self._on_ctrl_scroll)
        self.scroll.add_controller(scroll_ctrl)

        # Menu latéral droit
        self.side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.side.set_margin_start(8)
        self.side.set_margin_end(8)
        self.side.set_margin_top(8)
        self.side.set_margin_bottom(8)
        self.side.set_size_request(260, -1)
        main.append(self.side)

        # Contenu du menu latéral
        self.lbl_index = Gtk.Label(label="")
        self.lbl_index.set_use_markup(True)
        self.side.append(self.lbl_index)

        self.lbl_variant = Gtk.Label(label="")
        self.side.append(self.lbl_variant)

        self.lbl_student = Gtk.Label(label="")
        self.lbl_student.set_use_markup(True)
        self.lbl_student.set_wrap(True)
        self.side.append(self.lbl_student)

        self.lbl_note = Gtk.Label(label="")
        self.lbl_note.set_use_markup(True)
        self.side.append(self.lbl_note)

        self.lbl_status = Gtk.Label(label="")
        self.lbl_status.set_use_markup(True)
        self.side.append(self.lbl_status)

        self.side.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Édition manuelle du numéro étudiant
        self.side.append(Gtk.Label(label="N° étudiant :"))
        self.entry_student = Gtk.Entry()
        self.entry_student.set_max_length(8)
        self.entry_student.set_placeholder_text("p0000000")
        btn_apply_sid = Gtk.Button(label="Appliquer")
        btn_apply_sid.connect("clicked", self._on_apply_student_id)
        sid_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sid_box.append(self.entry_student)
        sid_box.append(btn_apply_sid)
        self.side.append(sid_box)

        self.side.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Navigation entre copies
        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_prev = Gtk.Button(label="‹ Précédent")
        self.btn_prev.connect("clicked", lambda _b: self._navigate(-1))
        self.btn_next = Gtk.Button(label="Suivant ›")
        self.btn_next.connect("clicked", lambda _b: self._navigate(+1))
        nav_box.append(self.btn_prev)
        nav_box.append(self.btn_next)
        self.side.append(nav_box)

        self._load_page()

    def _navigate(self, delta: int) -> None:
        n = len(self.pages)
        if n == 0:
            return
        self.idx = max(0, min(n - 1, self.idx + delta))
        if self.on_navigate is not None:
            self.on_navigate(self.idx)
        self._load_page()

    def _load_page(self) -> None:
        if self.idx < 0 or self.idx >= len(self.pages):
            return
        label, page = self.pages[self.idx]
        self._img = scanner.render_marked_page(page)
        n = len(self.pages)
        self.lbl_index.set_markup(f"<b>Copie {self.idx + 1} / {n}</b>")
        failed = page.matrix_inv is None or page.variant_id is None or page.student_id is None
        if failed:
            reason = "Échec alignement"
            if page.variant_id is not None and page.student_id is None:
                reason = "N° étudiant non trouvé"
            elif page.variant_id is None:
                reason = "Code-barres non trouvé"
            self.lbl_variant.set_text(f"Variante : {page.variant_id or '—'}")
            self.lbl_student.set_markup(f"<span color='#F00'><b>⚠ {reason}</b></span>")
            self.lbl_note.set_markup("<b><span size='large'>Note : —</span></b>")
            self.lbl_status.set_markup(f"<span color='#F00'>Non corrigée</span>")
        else:
            self.lbl_variant.set_text(f"Variante : {page.variant_id}")
            sid = page.student_id or "—"
            name = ""
            if page.student_name or page.student_firstname:
                name = f"\n{page.student_name or ''} {page.student_firstname or ''}".strip()
            self.lbl_student.set_markup(f"Étudiant : {sid}{name}")
            note = page.value if page.value is not None else 0.0
            total = page.total if page.total is not None else 20.0
            color = "#0F0" if page.complete else "#F00"
            self.lbl_note.set_markup(f"<b><span size='large'>Note : {note:.2f} / {total:.0f}</span></b>")
            status = "complète" if page.complete else "incomplète"
            self.lbl_status.set_markup(f"Statut : <span color='{color}'>{status}</span>")
        self.btn_prev.set_sensitive(self.idx > 0)
        self.btn_next.set_sensitive(self.idx < n - 1)
        self.entry_student.set_text(page.student_id or "")
        self.zoom_scale.set_value(self._zoom)
        self.zoom_label.set_text(f"{int(self._zoom * 100)} %")
        self._update_image()

    def _on_apply_student_id(self, _btn) -> None:
        if self.idx < 0 or self.idx >= len(self.pages):
            return
        _label, page = self.pages[self.idx]
        sid = self.entry_student.get_text().strip()
        if not sid:
            return
        page.student_id = sid
        if hasattr(self, "_project") and self._project is not None:
            student = self._project.students.get(sid)
            if student is not None:
                page.student_eid = student.eid
                page.student_name = student.name
                page.student_firstname = student.firstname
        self._load_page()

    def _on_ctrl_scroll(self, ctrl, dx, dy):
        state = ctrl.get_current_event_state()
        if not (state & Gdk.ModifierType.CONTROL_MASK):
            return
        step = -dy * 0.25
        if step == 0:
            step = -dx * 0.25
        self._set_zoom(self._zoom + step)

    def _set_zoom(self, value, from_scale=False):
        value = max(0.25, min(4.0, round(value * 4) / 4))
        if abs(value - self._zoom) < 0.01:
            return
        self._zoom = value
        if not from_scale:
            self.zoom_scale.set_value(value)
        self.zoom_label.set_text(f"{int(value * 100)} %")
        self._update_image()

    def _update_image(self):
        if self._img is None:
            return
        from PIL import Image as PILImage
        w = max(1, int(self._img.width * self._zoom))
        h = max(1, int(self._img.height * self._zoom))
        resized = self._img.resize((w, h), PILImage.LANCZOS)
        self.image.set_size_request(w, h)
        self.image.set_paintable(_img_to_texture(resized))

    def add_side_widget(self, widget):
        self.side.append(widget)


class QcmApplication(Gtk.Application):
    def __init__(self, project_path: str | None = None,
                 copies: list[str] | None = None):
        super().__init__(application_id="org.qcm_papier")
        self.project_path = project_path
        self.copies = copies

    def do_activate(self):
        win = QcmWindow(application=self)
        win.present()
        if self.project_path:
            win._load_project_from_path(self.project_path)
        if self.copies:
            for p in self.copies:
                win.copies.append(p)
                win._add_copy_row(p)
            win.marking_status.set_text(f"{len(win.copies)} copie(s) chargée(s).")
            win._on_correct(None)

def run(argv: list[str] | None = None, project_path: str | None = None,
        copies: list[str] | None = None) -> int:
    app = QcmApplication(project_path=project_path, copies=copies)
    return app.run(argv if argv is not None else [])
