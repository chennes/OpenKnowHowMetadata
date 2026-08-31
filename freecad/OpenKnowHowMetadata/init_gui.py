# SPDX-License-Identifier: CC0-1.0

"""
GUI entry point for the addon.

This file is imported by FreeCAD after __init__.py when the GUI is available.
It runs only in GUI mode and is the place for GUI-related initialization:
registering workbenches, toolbars, menus, and loading icons/translations.

FreeCAD loading sequence:
    1. freecad.<module_name>.__init__.py (headless, always runs)
    2. freecad.<module_name>.init_gui.py (GUI only, runs when GUI is available)

Keep this file fast - it runs on every FreeCAD GUI startup.
"""

from PySide import QtWidgets
import FreeCAD as App
import FreeCADGui as Gui

class SaveObserver:
    def slotFinishSaveDocument(self, doc, path):
        if path != doc.FileName:
            return



App.addDocumentObserver(SaveObserver())

