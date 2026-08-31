"""Éditeur de structure du QCM (exercices/questions/choix) en GTK 4.

Permet de créer, modifier et supprimer exercices, questions et choix, avec
leurs propriétés (gain, pénalité, type de question, barème de l'exercice).
Les modifications sont synchronisées avec un objet ``Project``.

Écrit pour GTK 4 (PyGObject) — utilise ``append``/``present`` au lieu de
``add``/``show_all`` de GTK 3.
"""

from __future__ import annotations

from typing import Callable

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

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

        # Barre d'outils.
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.append(toolbar)
        btn_add_ex = Gtk.Button(label="Nouvel exercice")
        btn_add_ex.connect("clicked", self._on_add_exercise)
        toolbar.append(btn_add_ex)
        toolbar.append(Gtk.Separator())
        # Label pour afficher l'intervalle de notes du QCM
        self.label_interval = Gtk.Label(label="Intervalle : ")
        toolbar.append(self.label_interval)

        # Liste des exercices (arbre).
        self.store = Gtk.TreeStore(str, str, object)  # nom, type, objet
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_headers_visible(False)
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn("Structure", renderer, text=0)
        self.tree.append_column(col)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_child(self.tree)
        self.append(scroll)

        # Panneau de propriétés.
        self.props_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.props_box.set_margin_top(6)
        self.append(self.props_box)

        # Sélection.
        select = self.tree.get_selection()
        select.connect("changed", self._on_selection_changed)

        self._fill_tree()

    def _notify(self) -> None:
        if self.on_change:
            self.on_change()

    def _fill_tree(self) -> None:
        self.store.clear()
        for i, exercise in enumerate(self.project.structure):
            ex_label = f"Exercice {i+1} : {exercise.name}"
            ex_iter = self.store.append(None, [ex_label, "exercise", exercise])
            for j, question in enumerate(exercise.questions):
                q_label = f"  Q{j+1} : {question.name}"
                q_iter = self.store.append(ex_iter, [q_label, "question", question])
                for k, choice in enumerate(question.choices):
                    c_label = f"    {choice.name}"
                    self.store.append(q_iter, [c_label, "choice", choice])
        self.tree.expand_all()
        self._update_interval_label()

    # ------------------------------------------------------------------
    # Ajout d'éléments
    # ------------------------------------------------------------------

    def _on_add_exercise(self, _btn) -> None:
        ex = Exercise(name=f"Exercice {len(self.project.structure)+1}",
                       index=len(self.project.structure))
        q = Question(name="Question 1", gain=1.0, penalty=0.5, single=True, index=0)
        q.choices = [
            Choice(name="A", correct=True, neutral=False, index=0),
            Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
            Choice(name="C", correct=False, neutral=True, index=2),
            Choice(name="D", correct=False, neutral=True, index=3),
        ]
        ex.questions = [q]
        self.project.structure.append(ex)
        self._fill_tree()
        self._notify()

    def add_question(self, exercise: Exercise) -> None:
        q = Question(name=f"Question {len(exercise.questions)+1}",
                     gain=1.0, penalty=0.5, single=True, index=len(exercise.questions))
        q.choices = [
            Choice(name="A", correct=True, neutral=False, index=0),
            Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
        ]
        exercise.questions.append(q)
        self._fill_tree()
        self._notify()

    def add_choice(self, question: Question) -> None:
        c = Choice(name=chr(ord("A") + len(question.choices)),
                   correct=False, neutral=True, index=len(question.choices))
        question.choices.append(c)
        self._fill_tree()
        self._notify()

    # ------------------------------------------------------------------
    # Sélection et propriétés
    # ------------------------------------------------------------------

    def _on_selection_changed(self, selection) -> None:
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
        elif kind == "choice":
            self._edit_choice(obj)

    def _row(self, label: str, widget: Gtk.Widget) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label=label))
        widget.set_hexpand(True)
        row.append(widget)
        return row

    def _edit_exercise(self, exercise: Exercise) -> None:
        name = Gtk.Entry(text=exercise.name)
        name.connect("changed", lambda e: self._set_and_notify(exercise, "name", e.get_text()))
        self.props_box.append(Gtk.Label(label="<b>Exercice</b>", use_markup=True))
        self.props_box.append(self._row("Nom :", name))

        btn_add_q = Gtk.Button(label="Ajouter une question")
        btn_add_q.connect("clicked", lambda _b: self.add_question(exercise))
        self.props_box.append(btn_add_q)

        # Barème.
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

    def _edit_question(self, question: Question) -> None:
        name = Gtk.Entry(text=question.name)
        name.connect("changed",
                     lambda e: self._set_and_notify(question, "name", e.get_text()))
        self.props_box.append(Gtk.Label(label="<b>Question</b>", use_markup=True))
        self.props_box.append(self._row("Nom :", name))

        gain = Gtk.SpinButton.new_with_range(0, 1000, 0.5)
        gain.set_value(question.gain)
        gain.connect("value-changed",
                     lambda b: self._set_and_notify(question, "gain", b.get_value()))
        self.props_box.append(self._row("Gain :", gain))
        penalty = Gtk.SpinButton.new_with_range(0, 1000, 0.5)
        penalty.set_value(question.penalty)
        penalty.connect("value-changed",
                       lambda b: self._set_and_notify(question, "penalty", b.get_value()))
        self.props_box.append(self._row("Malus :", penalty))

        # Type de question (CheckButton avec groupe en GTK 4).
        single = Gtk.CheckButton(label="Choix unique")
        single.set_active(question.single)
        multiple_exact = Gtk.CheckButton(label="Choix multiples (correspondance exacte)",
                                          group=single)
        multiple_exact.set_active(question.multiple_exact)
        multiple_prog = Gtk.CheckButton(label="Choix multiples (gain progressif)",
                                         group=single)
        multiple_prog.set_active(question.multiple_progressive)

        def on_type(_btn):
            self._set_and_notify(question, "single", single.get_active())
            self._set_and_notify(question, "multiple_exact", multiple_exact.get_active())
            self._set_and_notify(question, "multiple_progressive", multiple_prog.get_active())
        single.connect("toggled", on_type)
        multiple_exact.connect("toggled", on_type)
        multiple_prog.connect("toggled", on_type)
        self.props_box.append(Gtk.Label(label="Type :"))
        self.props_box.append(single)
        self.props_box.append(multiple_exact)
        self.props_box.append(multiple_prog)

        manual = Gtk.CheckButton(label="Correction manuelle (réponse libre)")
        manual.set_active(question.manual)
        manual.connect("toggled",
                       lambda b: self._set_and_notify(question, "manual", b.get_active()))
        self.props_box.append(manual)

        btn_add_c = Gtk.Button(label="Ajouter un choix")
        btn_add_c.connect("clicked", lambda _b: self.add_choice(question))
        self.props_box.append(btn_add_c)

    def _edit_choice(self, choice: Choice) -> None:
        name = Gtk.Entry(text=choice.name)
        name.connect("changed",
                     lambda e: self._set_and_notify(choice, "name", e.get_text()))
        self.props_box.append(Gtk.Label(label="<b>Choix</b>", use_markup=True))
        self.props_box.append(self._row("Nom :", name))

        correct = Gtk.CheckButton(label="Réponse correcte")
        correct.set_active(choice.correct)
        correct.connect("toggled",
                        lambda b: self._set_and_notify(choice, "correct", b.get_active()))
        self.props_box.append(correct)
        neutral = Gtk.CheckButton(label="Choix neutre")
        neutral.set_active(choice.neutral)
        neutral.connect("toggled",
                        lambda b: self._set_and_notify(choice, "neutral", b.get_active()))
        self.props_box.append(neutral)
        penalty = Gtk.CheckButton(label="Choix pénalisant")
        penalty.set_active(choice.penalty)
        penalty.connect("toggled",
                        lambda b: self._set_and_notify(choice, "penalty", b.get_active()))
        self.props_box.append(penalty)

    def _set_and_notify(self, obj, attr, value) -> None:
        setattr(obj, attr, value)
        self._fill_tree()
        self._update_interval_label()
        self._notify()

    def _update_interval_label(self) -> None:
        """Met à jour le label d'intervalle de notes avec les valeurs actuelles."""
        global_min, global_max = self.project.get_mark_range()
        # Utilise le symbole 🏆 comme dans l'original
        self.label_interval.set_text(f"Intervalle : {global_min:.1f} 🏆 {global_max:.1f}")
