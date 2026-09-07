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
from gi.repository import Gtk, Gdk

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

        self.notebook.append_page(box, Gtk.Label(label="Correction"))

    def _on_load_copies(self, _btn) -> None:
        path = _file_dialog(self, "Choisir les copies",
                            Gtk.FileChooserAction.OPEN,
                            filters=[("PDF et images", ["*.pdf", "*.png",
                                                         "*.jpg", "*.jpeg"])])
        if path is None:
            return
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
    # Menu
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
            
            # Debug: afficher les valeurs lues depuis le JSON
            import json
            with open(path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            print("\n=== DEBUG: VALEURS FANTÔMES DANS LE JSON ===")
            print(f"pos_exercise_new_exercises: {json_data.get('pos_exercise_new_exercises', '❌ NON TROUVÉ')}")
            print(f"pos_exercise_new_exercises_name: {json_data.get('pos_exercise_new_exercises_name', '❌ NON TROUVÉ')}")
            print(f"pos_exercise_new_questions: {json_data.get('pos_exercise_new_questions', '❌ NON TROUVÉ')}")
            print(f"pos_exercise_new_questions_name: {json_data.get('pos_exercise_new_questions_name', '❌ NON TROUVÉ')}")
            print(f"pos_exercise_new_choices: {json_data.get('pos_exercise_new_choices', '❌ NON TROUVÉ')}")
            print(f"pos_exercise_new_choices_name: {json_data.get('pos_exercise_new_choices_name', '❌ NON TROUVÉ')}")
            print(f"pos_question_new_questions: {json_data.get('pos_question_new_questions', '❌ NON TROUVÉ')}")
            print(f"pos_question_new_questions_name: {json_data.get('pos_question_new_questions_name', '❌ NON TROUVÉ')}")
            print(f"pos_question_new_choices: {json_data.get('pos_question_new_choices', '❌ NON TROUVÉ')}")
            print(f"pos_question_new_choices_name: {json_data.get('pos_question_new_choices_name', '❌ NON TROUVÉ')}")
            print(f"pos_choice_new_choices: {json_data.get('pos_choice_new_choices', '❌ NON TROUVÉ')}")
            print(f"pos_choice_new_choices_name: {json_data.get('pos_choice_new_choices_name', '❌ NON TROUVÉ')}")
            
            print("\n=== DEBUG: VALEURS DANS ProjectSettings ===")
            print(f"exercise_new_exercises: {self.project.settings.exercise_new_exercises}")
            print(f"exercise_new_exercises_name: {self.project.settings.exercise_new_exercises_name}")
            print(f"exercise_new_questions: {self.project.settings.exercise_new_questions}")
            print(f"exercise_new_questions_name: {self.project.settings.exercise_new_questions_name}")
            print(f"exercise_new_choices: {self.project.settings.exercise_new_choices}")
            print(f"exercise_new_choices_name: {self.project.settings.exercise_new_choices_name}")
            print(f"question_new_questions: {self.project.settings.question_new_questions}")
            print(f"question_new_questions_name: {self.project.settings.question_new_questions_name}")
            print(f"question_new_choices: {self.project.settings.question_new_choices}")
            print(f"question_new_choices_name: {self.project.settings.question_new_choices_name}")
            print(f"choice_new_choices: {self.project.settings.choice_new_choices}")
            print(f"choice_new_choices_name: {self.project.settings.choice_new_choices_name}")
            
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

class QcmApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.qcm_papier")

    def do_activate(self):
        win = QcmWindow(application=self)
        win.present()

def run(argv: list[str] | None = None) -> int:
    app = QcmApplication()
    return app.run(argv if argv is not None else [])
