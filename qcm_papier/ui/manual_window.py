"""Fenêtre GTK de notation des questions à réponse libre.

Même principe que l'interface web : on note question par question sur toutes
les copies, avec le cadre de réponse découpé dans le scan et, à côté, l'aide à
la correction (réponse attendue, éléments de correction), masquable.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from .. import manual_grading, markdown_pango
from ..model import Project

ANSWER_MAX_WIDTH = 560  # px : largeur maximale du cadre affiché


def _texture(img) -> Gdk.Texture:
    buf = io.BytesIO()
    img.save(buf, format="png")
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(buf.getvalue()))


def _points(value: float) -> str:
    return f"{value:g}".replace(".", ",")


class ManualGradingWindow(Gtk.Window):
    """Notation des réponses libres des pages corrigées.

    ``marked_pages`` est la liste ``(libellé, page)`` de la fenêtre principale ;
    ``describe(i)`` renvoie (étudiant, fichier) de la page ``i`` et
    ``on_change(i)`` est appelé après chaque saisie (mise à jour du tableau).
    """

    def __init__(
        self,
        project: Project,
        marked_pages: list,
        describe: Callable[[int], tuple[str, str]],
        on_change: Callable[[int], None],
        parent=None,
    ):
        super().__init__(
            title="Questions à réponse libre",
            transient_for=parent,
            default_width=1150,
            default_height=800,
            modal=False,
            destroy_with_parent=True,
        )
        self.project = project
        self.pages = marked_pages
        self.describe = describe
        self.on_change = on_change
        self.questions = manual_grading.open_questions(project)
        self.current = 0
        self.entries: list[Gtk.Entry] = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("start", "end", "top", "bottom"):
            getattr(root, f"set_margin_{side}")(8)
        self.set_child(root)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.append(Gtk.Label(label="Question :"))
        self.question_dropdown = Gtk.DropDown.new_from_strings(self._question_labels())
        self.question_dropdown.connect("notify::selected", self._on_question_selected)
        bar.append(self.question_dropdown)
        self.todo_check = Gtk.CheckButton(label="Seulement les réponses à noter")
        self.todo_check.connect("toggled", lambda _b: self._fill_rows())
        bar.append(self.todo_check)
        self.help_check = Gtk.CheckButton(label="Aide à la correction", active=True)
        self.help_check.connect("toggled", lambda b: self.help_panel.set_visible(b.get_active()))
        bar.append(self.help_check)
        self.progress = Gtk.Label(xalign=0)
        self.progress.get_style_context().add_class("dim-label")
        bar.append(self.progress)
        root.append(bar)

        self.status = Gtk.Label(xalign=0)
        root.append(self.status)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        body.set_vexpand(True)
        root.append(body)

        self.rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        # Pas de défilement horizontal : l'image du cadre rétrécit, la colonne des points reste visible.
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.rows)
        body.append(scroll)

        self.help_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.expected_label = self._help_section("Réponse attendue")
        self.notes_label = self._help_section("Éléments de correction")
        # La case à cocher masque tout le panneau, barre de défilement comprise.
        self.help_panel = Gtk.ScrolledWindow(vexpand=True)
        self.help_panel.set_child(self.help_box)
        self.help_panel.set_size_request(300, -1)
        body.append(self.help_panel)

        self._fill_rows()

    # ------------------------------------------------------------------
    def _help_section(self, title: str) -> Gtk.Label:
        self.help_box.append(Gtk.Label(label=f"<b>{title}</b>", use_markup=True, xalign=0))
        text = Gtk.Label(xalign=0, wrap=True, selectable=True)
        text.set_max_width_chars(40)
        self.help_box.append(text)
        return text

    def _rows_of(self, e: int, q: int) -> list[tuple[int, dict]]:
        rows = []
        for index, (_label, page) in enumerate(self.pages):
            mark = manual_grading.answer_mark(page, e, q)
            if mark is not None:
                rows.append((index, mark))
        return rows

    def _question_labels(self) -> list[str]:
        labels = []
        for e, q, exercise, question in self.questions:
            remaining = sum(1 for _i, mark in self._rows_of(e, q) if mark.get("value") is None)
            labels.append(f"{exercise.name} — {question.name} ({remaining} à noter)")
        return labels or ["Aucune question à réponse libre"]

    def _on_question_selected(self, dropdown, _pspec) -> None:
        selected = dropdown.get_selected()
        if 0 <= selected < len(self.questions) and selected != self.current:
            self.current = selected
            self._fill_rows()

    def _update_progress(self) -> None:
        if not self.questions:
            self.progress.set_text("")
            return
        e, q, _exercise, question = self.questions[self.current]
        rows = self._rows_of(e, q)
        done = sum(1 for _i, mark in rows if mark.get("value") is not None)
        self.progress.set_text(f"{done}/{len(rows)} notée(s), sur {_points(question.gain)} pt")
        # Le compteur « à noter » de la liste déroulante suit la saisie.
        model = self.question_dropdown.get_model()
        if isinstance(model, Gtk.StringList):
            labels = self._question_labels()
            model.splice(self.current, 1, [labels[self.current]])

    def _fill_rows(self) -> None:
        for child in list(self.rows):
            self.rows.remove(child)
        self.entries = []
        if not self.questions:
            self.rows.append(Gtk.Label(label="Le projet ne contient aucune question à réponse libre."))
            self.help_panel.set_visible(False)
            return
        e, q, _exercise, question = self.questions[self.current]
        none = "<i>Non renseigné (onglet Structure).</i>"
        self.expected_label.set_markup(markdown_pango.render(question.expected) if question.expected else none)
        self.notes_label.set_markup(markdown_pango.render(question.grading_notes) if question.grading_notes else none)
        rows = self._rows_of(e, q)
        if self.todo_check.get_active():
            rows = [(i, mark) for i, mark in rows if mark.get("value") is None]
        for index, mark in rows:
            self.rows.append(self._row(e, q, index, mark))
        if not rows:
            self.rows.append(Gtk.Label(label="Toutes les réponses sont notées."))
        self._update_progress()

    def _row(self, e: int, q: int, index: int, mark: dict) -> Gtk.Widget:
        question = self.project.structure[e].questions[q]
        who, file_name = self.describe(index)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for side in ("start", "end", "top", "bottom"):
            getattr(row, f"set_margin_{side}")(6)

        ident = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        ident.set_size_request(150, -1)
        ident.append(
            Gtk.Label(
                label=f"<b>{GLib.markup_escape_text(who or 'Étudiant non identifié')}</b>",
                use_markup=True,
                xalign=0,
                wrap=True,
            )
        )
        file_label = Gtk.Label(label=file_name, xalign=0, wrap=True)
        file_label.get_style_context().add_class("dim-label")
        ident.append(file_label)
        row.append(ident)

        try:
            crop = manual_grading.crop_answer(self.pages[index][1], e, q)
            if crop.width > ANSWER_MAX_WIDTH:
                crop = crop.resize((ANSWER_MAX_WIDTH, round(crop.height * ANSWER_MAX_WIDTH / crop.width)))
            picture = Gtk.Picture.new_for_paintable(_texture(crop))
            picture.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
            picture.set_size_request(200, min(crop.height, 220))
            picture.set_hexpand(True)
            picture.set_halign(Gtk.Align.START)
            row.append(picture)
        except ValueError as err:
            row.append(Gtk.Label(label=str(err), hexpand=True))

        points = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        points.set_valign(Gtk.Align.CENTER)
        points.set_hexpand(False)
        entry = Gtk.Entry(width_chars=6, placeholder_text="Points")
        entry.set_text("" if mark.get("value") is None else _points(mark["value"]))
        self.entries.append(entry)
        quick = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for value, label in ((0.0, "0"), (question.gain / 2, "½"), (float(question.gain), _points(question.gain))):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _b, v=value: self._save(e, q, index, v, entry, advance=True))
            quick.append(button)
        points.append(quick)
        points.append(entry)
        entry.connect("activate", lambda en: self._save_text(e, q, index, en))
        clear = Gtk.Button(label="Effacer")
        clear.connect("clicked", lambda _b: self._save(e, q, index, None, entry))
        points.append(clear)
        row.append(points)
        return row

    def _save_text(self, e: int, q: int, index: int, entry: Gtk.Entry) -> None:
        try:
            value = manual_grading.parse_points(entry.get_text())
        except ValueError as err:
            self._error(str(err))
            return
        self._save(e, q, index, value, entry, advance=True)

    def _save(self, e: int, q: int, index: int, value: float | None, entry: Gtk.Entry, advance: bool = False) -> None:
        try:
            manual_grading.set_answer_value(self.project, self.pages[index][1], e, q, value)
        except ValueError as err:
            self._error(str(err))
            return
        self.status.set_text("")
        entry.set_text("" if value is None else _points(value))
        self.on_change(index)
        self._update_progress()
        if advance:
            position = self.entries.index(entry)
            if position + 1 < len(self.entries):
                following = self.entries[position + 1]
                following.grab_focus()

    def _error(self, message: str) -> None:
        self.status.set_markup(f"<span color='#C62828'>{GLib.markup_escape_text(message)}</span>")
