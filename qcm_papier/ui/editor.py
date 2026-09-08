"""Éditeur de structure du QCM (exercices/questions/choix) en GTK 4."""

from __future__ import annotations
from typing import Callable
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GLib
from ..model import Choice, Exercise, Project, Question

class StructureEditor(Gtk.Box):
    """Panneau d'édition de la structure du QCM."""

    def __init__(self, project: Project, on_change: Callable[[], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.project = project
        self.on_change = on_change
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(8)
        self.set_margin_bottom(8)

        # Variable pour bloquer les mises à jour pendant les modifications
        self._updating = False
        self._update_id = None

        # Barre d'outils.
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.append(toolbar)
        btn_add_ex = Gtk.Button(label="Nouvel exercice")
        btn_add_ex.connect("clicked", self._on_add_exercise)
        toolbar.append(btn_add_ex)
        toolbar.append(Gtk.Separator())
        self.label_interval = Gtk.Label(label="Intervalle : ")
        toolbar.append(self.label_interval)

        # Liste des exercices
        self.store = Gtk.TreeStore(str, str, object)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_headers_visible(False)
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn("Structure", renderer, markup=0)
        self.tree.append_column(col)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_child(self.tree)
        self.append(scroll)

        # Panneau de propriétés
        self.props_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.props_box.set_margin_top(6)
        self.append(self.props_box)

        # Sélection
        self.selection = self.tree.get_selection()
        self.selection.connect("changed", self._on_selection_changed)
        self.tree.connect("row-activated", self._on_row_activated)

        self.current_popover = None

        # Désactiver les animations CSS
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            * {
                transition: none;
                animation: none;
            }
        """)

        self.get_style_context().add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._fill_tree()

    def _get_choice_color(self, choice):
        """Retourne la couleur selon l'état du choix."""
        if choice.correct:
            return "#00aa00"  # Vert
        elif choice.neutral:
            return "#0000ff"  # Bleu
        elif choice.penalty:
            return "#ff0000"  # Rouge
        return "#000000"  # Noir

    def _normalize_single_choices(self, question):
        """Assure qu'il y a exactement un choix correct en mode single."""
        if question.single and question.choices:
            correct_choices = [c for c in question.choices if c.correct]

            if len(correct_choices) == 0:
                # Aucun choix correct → le premier devient correct
                question.choices[0].correct = True
                question.choices[0].neutral = False
                question.choices[0].penalty = False
            elif len(correct_choices) > 1:
                # Plusieurs choix corrects → ne garder que le premier
                first_correct = correct_choices[0]
                for c in correct_choices[1:]:
                    c.correct = False
                    c.neutral = True
                    c.penalty = False

    def _notify(self):
        """Notifie les changements."""
        if self.on_change and not self._updating:
            self.on_change()

    def _fill_tree(self):
        """Remplit l'arbre avec les données du projet."""
        if self._updating:
            return

        self._updating = True
        self.tree.set_sensitive(False)

        try:
            # Sauvegarder l'objet sélectionné
            model, treeiter = self.selection.get_selected()
            selected_obj = model[treeiter][2] if treeiter else None

            self.store.freeze_notify()
            self.store.clear()

            selected_iter = None
            for i, exercise in enumerate(self.project.structure):
                ex_min, ex_max = exercise.get_mark_range()
                ex_label = f"Exercice {i+1} : {exercise.name} {ex_min:.1f} 🡕 {ex_max:.1f}"
                ex_iter = self.store.append(None, [ex_label, "exercise", exercise])

                if selected_obj is exercise:
                    selected_iter = ex_iter

                for j, question in enumerate(exercise.questions):
                    q_min, q_max = question.get_mark_range()
                    choices_str = " ".join([f'<span foreground="{self._get_choice_color(c)}">({c.name})</span>'
                                          for c in question.choices])
                    q_label = f"  Q{j+1} : {question.name} {q_min} 🡕 {q_max} {choices_str}"
                    q_iter = self.store.append(ex_iter, [q_label, "question", question])

                    if selected_obj is question:
                        selected_iter = q_iter

            self.store.thaw_notify()
            self.tree.expand_all()

            # Restaurer la sélection
            if selected_iter:
                GLib.idle_add(lambda: self.selection.select_iter(selected_iter))

        finally:
            self.tree.set_sensitive(True)
            self._updating = False
            self._update_interval_label()

    def _schedule_update(self):
        """Planifie une mise à jour différée."""
        if self._update_id is None:
            self._update_id = GLib.idle_add(self._do_update)

    def _do_update(self):
        """Effectue la mise à jour différée."""
        if not self._updating:
            self._fill_tree()
            self._notify()
        if self._update_id is not None:
            GLib.source_remove(self._update_id)
            self._update_id = None
        return False

    def _update_interval_label(self):
        """Met à jour le label d'intervalle de notes."""
        global_min, global_max = self.project.get_mark_range()
        self.label_interval.set_text(f"Intervalle : {global_min:.1f} 🡕 {global_max:.1f}")

    def _on_add_exercise(self, _btn):
        """Ajoute un nouvel exercice avec 8 choix par défaut."""
        ex = Exercise(name=f"Exercice {len(self.project.structure)+1}",
                      index=len(self.project.structure))
        q = Question(name="Question 1", gain=1.0, penalty=0.5, single=True, index=0)
        q.choices = [
            Choice(name="A", correct=True, neutral=False, index=0),
            Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
            Choice(name="C", correct=False, neutral=True, index=2),
            Choice(name="D", correct=False, neutral=True, index=3),
            Choice(name="E", correct=False, neutral=True, index=4),
            Choice(name="F", correct=False, neutral=True, index=5),
            Choice(name="G", correct=False, neutral=True, index=6),
            Choice(name="H", correct=False, neutral=True, index=7),
        ]
        ex.questions = [q]
        self.project.structure.append(ex)
        self._schedule_update()

    def add_question(self, exercise):
        """Ajoute une nouvelle question avec 8 choix par défaut."""
        q = Question(name=f"Question {len(exercise.questions)+1}",
                    gain=1.0, penalty=0.5, single=True, index=len(exercise.questions))
        q.choices = [
            Choice(name="A", correct=True, neutral=False, index=0),
            Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
            Choice(name="C", correct=False, neutral=True, index=2),
            Choice(name="D", correct=False, neutral=True, index=3),
            Choice(name="E", correct=False, neutral=True, index=4),
            Choice(name="F", correct=False, neutral=True, index=5),
            Choice(name="G", correct=False, neutral=True, index=6),
            Choice(name="H", correct=False, neutral=True, index=7),
        ]
        exercise.questions.append(q)
        self._schedule_update()

    def add_choice(self, question):
        """Ajoute un nouveau choix."""
        c = Choice(name=chr(ord("A") + len(question.choices)),
                  correct=False, neutral=True, index=len(question.choices))
        question.choices.append(c)
        if question.single and len(question.choices) == 1:
            c.correct = True
            c.neutral = False
            c.penalty = False
        self._normalize_single_choices(question)
        self._schedule_update()

    def remove_choice(self, question):
        """Supprime le dernier choix de la question si possible."""
        if len(question.choices) > 1:
            question.choices.pop()
            if question.single:
                self._normalize_single_choices(question)
            self._schedule_update()

    def _on_row_activated(self, treeview, path, column):
        """Gère le double-clic sur une ligne."""
        model = treeview.get_model()
        treeiter = model.get_iter(path)
        if treeiter:
            kind = model[treeiter][1]
            obj = model[treeiter][2]
            if kind == "question":
                self._show_choice_menu(treeview, path, column, obj)

    def _show_choice_menu(self, treeview, path, column, question):
        """Affiche le menu pour modifier les états des choix."""
        if self.current_popover:
            self.current_popover.popdown()
            self.current_popover = None

        self.current_popover = Gtk.PopoverMenu()
        self.current_popover.set_parent(treeview)
        self.current_popover.set_autohide(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        self.current_popover.set_child(box)

        for choice in question.choices:
            choice_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            label = Gtk.Label(label=f"{choice.name})")
            label.set_halign(Gtk.Align.START)
            choice_box.append(label)

            state_dropdown = Gtk.DropDown.new_from_strings(["Correct", "Neutre", "Faux"])
            state_dropdown.set_selected(self._get_choice_state_index(choice))
            state_dropdown.connect("notify::selected", self._on_state_changed, choice, question)
            choice_box.append(state_dropdown)
            box.append(choice_box)

        cell_area = treeview.get_cell_area(path, column)
        if cell_area:
            rect = Gdk.Rectangle()
            rect.x = cell_area.x
            rect.y = cell_area.y + cell_area.height
            rect.width = 1
            rect.height = 1
            self.current_popover.set_pointing_to(rect)

        GLib.idle_add(lambda: self.current_popover.popup())

    def _get_choice_state_index(self, choice):
        """Retourne l'index de l'état pour le menu déroulant."""
        if choice.correct:
            return 0
        elif choice.neutral:
            return 1
        elif choice.penalty:
            return 2
        return 1

    def _on_state_changed(self, dropdown, _pspec, choice, question):
        """Gère le changement d'état avec gestion du mode single."""
        selected = dropdown.get_selected()

        # Bloquer la désélection du dernier choix correct en mode single
        if selected != 0 and question.single:
            correct_choices = [c for c in question.choices if c.correct]
            if len(correct_choices) == 1 and choice in correct_choices:
                GLib.idle_add(lambda: dropdown.set_selected(0))
                return

        # Gestion du mode single
        if selected == 0 and question.single:
            for c in question.choices:
                if c != choice and c.correct:
                    c.correct = False
                    c.neutral = True
                    c.penalty = False

        # Appliquer le nouvel état
        if selected == 0:
            choice.correct = True
            choice.neutral = False
            choice.penalty = False
        elif selected == 1:
            choice.correct = False
            choice.neutral = True
            choice.penalty = False
        elif selected == 2:
            choice.correct = False
            choice.neutral = False
            choice.penalty = True

        self._normalize_single_choices(question)
        self._schedule_update()

    def _on_selection_changed(self, selection):
        """Gère le changement de sélection dans l'arbre."""
        model, treeiter = selection.get_selected()
        for child in list(self.props_box):
            self.props_box.remove(child)

        if treeiter is None:
            return

        kind = model[treeiter][1]
        obj = model[treeiter][2]
        if kind == "exercise":
            self._edit_exercise(obj)
        elif kind == "question":
            self._edit_question(obj)

    def _row(self, label, widget):
        """Crée une ligne pour le panneau de propriétés."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label=label))
        widget.set_hexpand(True)
        row.append(widget)
        return row

    def _edit_exercise(self, exercise):
        """Affiche les propriétés d'un exercice."""
        name = Gtk.Entry(text=exercise.name)
        name.connect("changed", lambda e: self._set_and_notify(exercise, "name", e.get_text()))
        name.connect("focus-out", lambda e: self.tree.grab_focus())
        self.props_box.append(Gtk.Label(label="<b>Exercice</b>", use_markup=True))
        self.props_box.append(self._row("Nom :", name))

        btn_add_q = Gtk.Button(label="Ajouter une question")
        btn_add_q.connect("clicked", lambda _b: self.add_question(exercise))
        self.props_box.append(btn_add_q)

        validation = Gtk.CheckButton(label="Validation par seuil")
        validation.set_active(exercise.validation)
        validation.connect("toggled",
                          lambda b: self._set_and_notify(exercise, "validation", b.get_active()))
        self.props_box.append(validation)

        gain = Gtk.SpinButton.new_with_range(0, 1000, 0.5)
        gain.set_value(exercise.gain)
        gain.connect("value-changed",
                    lambda b: self._set_and_notify(exercise, "gain", b.get_value()))
        self.props_box.append(self._row("Gain si validé :", gain))

        threshold = Gtk.SpinButton.new_with_range(0, 1000, 0.5)
        threshold.set_value(exercise.threshold)
        threshold.connect("value-changed",
                         lambda b: self._set_and_notify(exercise, "threshold", b.get_value()))
        self.props_box.append(self._row("Seuil :", threshold))

        min0 = Gtk.CheckButton(label="Note minimale 0 (pas de points négatifs)")
        min0.set_active(exercise.min0)
        min0.connect("toggled",
                    lambda b: self._set_and_notify(exercise, "min0", b.get_active()))
        self.props_box.append(min0)

    def _edit_question(self, question):
        """Affiche les propriétés d'une question."""
        name = Gtk.Entry(text=question.name)
        name.connect("changed",
                    lambda e: self._set_and_notify(question, "name", e.get_text()))
        name.connect("focus-out", lambda e: self.tree.grab_focus())
        self.props_box.append(Gtk.Label(label="<b>Question</b>", use_markup=True))
        self.props_box.append(self._row("Nom :", name))

        # 🔧 Gain, Malus et boutons sur la même ligne
        line_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        gain_label = Gtk.Label(label="Gain :")
        gain = Gtk.SpinButton.new_with_range(0, 1000, 0.5)
        gain.set_value(question.gain)
        gain.set_hexpand(True)
        gain.connect("value-changed", lambda b: self._set_and_notify(question, "gain", b.get_value()))
        line_box.append(gain_label)
        line_box.append(gain)

        penalty_label = Gtk.Label(label="Malus :")
        penalty = Gtk.SpinButton.new_with_range(0, 1000, 0.5)
        penalty.set_value(question.penalty)
        penalty.set_hexpand(True)
        penalty.connect("value-changed", lambda b: self._set_and_notify(question, "penalty", b.get_value()))
        line_box.append(penalty_label)
        line_box.append(penalty)

        btn_add_c = Gtk.Button(label="Ajouter un choix")
        btn_add_c.connect("clicked", lambda _b: self.add_choice(question))
        line_box.append(btn_add_c)

        btn_remove_c = Gtk.Button(label="Enlever un choix")
        btn_remove_c.connect("clicked", lambda _b: self.remove_choice(question))
        line_box.append(btn_remove_c)

        self.props_box.append(line_box)

        # 🔧 Type de question SUR LA MÊME LIGNE
        type_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        type_label = Gtk.Label(label="Type de question :")
        type_dropdown = Gtk.DropDown.new_from_strings([
            "Choix unique",
            "Choix multiples à correspondance exacte (toute erreur ou omission entraîne le malus)",
            "Choix multiples à gain progressif (gain dégressif en fonction des omissions, toute erreur entraîne le malus)",
            "Correction manuelle (réponse libre)"
        ])

        if question.manual:
            selected_index = 3
        elif question.single:
            selected_index = 0
        elif question.multiple_exact:
            selected_index = 1
        else:
            selected_index = 2

        type_dropdown.set_selected(selected_index)
        type_dropdown.connect("notify::selected", self._on_question_type_changed, question)

        type_box.append(type_label)
        type_box.append(type_dropdown)
        self.props_box.append(type_box)
    

    def _on_question_type_changed(self, dropdown, _pspec, question):
        """Gère le changement de type de question."""
        selected = dropdown.get_selected()

        question.single = False
        question.multiple_exact = False
        question.multiple_progressive = False
        question.manual = False

        if selected == 0:
            question.single = True
            self._normalize_single_choices(question)
        elif selected == 1:
            question.multiple_exact = True
        elif selected == 2:
            question.multiple_progressive = True
        elif selected == 3:
            question.manual = True

        self._schedule_update()

    def _set_and_notify(self, obj, attr, value):
        """Modifie un attribut et notifie les changements."""
        old_value = getattr(obj, attr, None)
        setattr(obj, attr, value)

        if attr == "single" and value and isinstance(obj, Question):
            self._normalize_single_choices(obj)

        self._schedule_update()
