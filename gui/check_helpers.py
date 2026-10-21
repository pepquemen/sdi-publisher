"""
"Select all / Deselect all" toggle shared by every page with checkable lists.

Works with a QListWidget (every item) or a QTableWidget (the checkable item
in ``column``). Only VISIBLE rows are touched, so it respects the page's
filters. The label follows the current state: if every visible row is
already checked it offers "Deselect all", otherwise "Select all".
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QPushButton, QListWidget, QTableWidget


def _checkable_items(widget, column):
    if isinstance(widget, QListWidget):
        for i in range(widget.count()):
            item = widget.item(i)
            if item is not None and not item.isHidden() and item.flags() & Qt.ItemIsUserCheckable:
                yield item
    elif isinstance(widget, QTableWidget):
        for row in range(widget.rowCount()):
            if widget.isRowHidden(row):
                continue
            item = widget.item(row, column)
            if item is not None and item.flags() & Qt.ItemIsUserCheckable:
                yield item


def make_select_all_button(widget, column=0, parent=None):
    btn = QPushButton("Select all", parent)
    btn.setProperty("flat", "true")
    btn.setToolTip("Check / uncheck every visible row")

    def all_checked():
        items = list(_checkable_items(widget, column))
        return bool(items) and all(i.checkState() == Qt.Checked for i in items)

    def update_label(*_):
        try:
            btn.setText("Deselect all" if all_checked() else "Select all")
            btn.setEnabled(any(True for _ in _checkable_items(widget, column)))
        except RuntimeError:
            pass   # widget already deleted

    def toggle():
        state = Qt.Unchecked if all_checked() else Qt.Checked
        for item in list(_checkable_items(widget, column)):
            item.setCheckState(state)
        update_label()

    btn.clicked.connect(toggle)
    widget.itemChanged.connect(update_label)
    model = widget.model()
    model.rowsInserted.connect(update_label)
    model.rowsRemoved.connect(update_label)
    model.modelReset.connect(update_label)
    update_label()
    return btn
