"""Import de la table étudiants et export des notes Scodoc.

Reproduit ``MarkingScodocNamesLoad`` et ``MarkingScodocExportLoad`` du code
JavaScript original (index.html lignes ~7469-7700) :

* **Import de la table étudiants** : feuille Excel (XLS/XLSX) dont la première
  ligne contient les en-têtes ``etudid``, ``code_nip``, ``nom``, ``prenom``.
  On construit une table ``students`` indexée par ``'p' + nip[1:]``.
* **Export des notes** : feuille de notes Scodoc (XLS) où la première colonne
  contient ``!EID`` pour chaque étudiant (à partir de la ligne 8), et la
  colonne 5 (index 4) reçoit la note ramenée à ``/20``.
"""

from __future__ import annotations

from typing import Any

from openpyxl import load_workbook, Workbook
from openpyxl.utils import get_column_letter

from .model import Student


# ---------------------------------------------------------------------------
# Import de la table étudiants
# ---------------------------------------------------------------------------

# En-têtes attendus (code original : 'etudid', 'code_nip', 'nom', 'prenom').
_HEADER_EID = "etudid"
_HEADER_NIP = "code_nip"
_HEADER_NAME = "nom"
_HEADER_FIRSTNAME = "prenom"


def load_students_table(path: str) -> dict[str, Student]:
    """Charge une table étudiants Scodoc (XLS/XLSX).

    Reprend ``MarkingScodocNamesLoad`` (index.html ~7469-7545). Renvoie un dict
    ``students`` indexé par ``'p' + nip[1:]`` (le nip Scodoc commence par 'p').
    """
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    # Première ligne : en-têtes.
    header = next(rows, None)
    if header is None:
        return {}
    col_eid = col_nip = col_name = col_firstname = None
    for c, value in enumerate(header):
        if value == _HEADER_EID:
            col_eid = c
        elif value == _HEADER_NIP:
            col_nip = c
        elif value == _HEADER_NAME:
            col_name = c
        elif value == _HEADER_FIRSTNAME:
            col_firstname = c
    if None in (col_eid, col_nip, col_name, col_firstname):
        raise ValueError(
            "La feuille doit contenir les colonnes 'etudid', 'code_nip', "
            "'nom', 'prenom'."
        )

    students: dict[str, Student] = {}
    for row in rows:
        if col_eid >= len(row) or col_nip >= len(row):
            continue
        eid = str(row[col_eid] or "")
        nip = str(row[col_nip] or "")
        name = str(row[col_name] or "")
        firstname = str(row[col_firstname] or "")
        if not nip:
            continue
        # L'id étudiant est 'p' + les 7 chiffres après le 'p' initial.
        student_id = "p" + (nip[1:] if nip.startswith("p") else nip)
        students[student_id] = Student(
            id=student_id, eid=eid, nip=nip, name=name, firstname=firstname,
        )
    wb.close()
    return students


# ---------------------------------------------------------------------------
# Export des notes Scodoc
# ---------------------------------------------------------------------------

def export_scodoc_notes(path_input: str, path_output: str,
                        notes: dict[str, float],
                        note_max: float = 20.0, notemax: float = 20.0,
                        header_row: int = 7) -> int:
    """Injecte les notes dans une feuille Scodoc et sauvegarde en XLS.

    Reprend ``MarkingScodocExportLoad`` (index.html ~7625-7710) :

    * On lit la feuille d'entrée (XLS/XLSX).
    * Pour chaque ligne ``r > header_row`` dont la colonne 0 (A) commence par
      ``'!'``, l'EID est ``cellule[1:]``.
    * La note est cherchée dans ``notes`` (clé = EID), ramenée à
      ``note_max/notemax`` et écrite dans la colonne 5 (E), au format
      ``'x,xx'`` (virgule décimale).
    * On sauvegarde en ``.xls`` (format biff8 via openpyxl → en pratique on
      écrit du XLSX/OpenDocument compatible).

    Renvoie le nombre de notes injectées.
    """
    wb = load_workbook(path_input, data_only=True)
    ws = wb.active
    count = 0
    for r in range(header_row + 1, ws.max_row + 1):
        cell_a = ws.cell(row=r, column=1).value
        if cell_a is None:
            continue
        text = str(cell_a)
        if not text or text[0] != "!":
            continue
        eid = text[1:]
        value = notes.get(eid)
        if value is None:
            continue
        # Note ramenée à /20 (NOTEMAX).
        note = value * note_max / notemax
        ws.cell(row=r, column=5).value = f"{note:.2f}".replace(".", ",")
        count += 1

    # Sauvegarde : openpyxl ne supporte pas biff8 (.xls) ; on sauve en .xls
    # via le moteur par défaut si l'extension est .xls (sinon xlsx).
    out = path_output
    if out.lower().endswith(".xls") and not out.lower().endswith(".xlsx"):
        out = out[:-4] + ".xlsx"
    wb.save(out)
    wb.close()
    return count


def find_page_note(eid: str, papers_notes: list[tuple[str, float | None]]) -> float | None:
    """Cherche la note associée à un EID parmi une liste (eid, note).

    Helper reproduisant ``findPage(EID)`` du code original
    (index.html ~7660-7675).
    """
    for page_eid, note in papers_notes:
        if page_eid == eid and note is not None:
            return note
    return None
