"""Synthetic offline graph/panel UI validation and Windows screenshot capture."""
import argparse
import ctypes
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_graph_ui import GraphUITests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".validation/graph-ui")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    test = GraphUITests()
    with patch.object(socket, "create_connection", side_effect=AssertionError("No network in graph smoke")):
        test.setUp()
        try:
            app, root = test.app, test.root
            app.notes.insert("1.0", "A sustained deficit followed by victory.\nGold and XP determine this category independently of the model.")
            app.store.pin(42, "Pinned player")
            app.reload()
            app.match_tree.selection_set(["180"], focus="180")
            app.select_match()
            failures = []
            steps = iter((("1540x920", False, "graph-normal"),
                          ("1100x720", False, "graph-compact"),
                          ("1100x720", True, "graph-panels-expanded")))
            # Capture this HWND on its owning thread. Cross-process PrintWindow
            # can leave Tk's native paint dispatch blocked with nested canvases.
            from PIL import ImageGrab
            def advance():
                try:
                    geometry, expanded, name = next(steps)
                except StopIteration:
                    root.quit()
                    return
                print(f"Preparing {name}", flush=True)
                root.geometry(geometry)
                for panel in (app.accounts_panel, app.chat_panel):
                    if panel.expanded != expanded:
                        panel.toggle()
                def capture():
                    try:
                        test.assert_usable()
                        assert app.graph_view.readout.winfo_ismapped()
                        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
                        ImageGrab.grab(window=hwnd).save(args.output / f"{name}.png")
                        print(f"Captured {name}", flush=True)
                        root.after(100, advance)
                    except Exception as exc:
                        failures.append(exc)
                        root.quit()
                root.after(350, capture)
            root.after(100, advance)
            root.after(90000, lambda: (failures.append(RuntimeError("Screenshot smoke timeout")), root.quit()))
            root.mainloop()
            if failures:
                raise failures[0]
            assert "keep" not in app.notes.get("1.0", "end")
            app.category_filter.set("Stomp")
            app.filter_changed()
            assert not app.visible
            app.category_filter.set("Comeback")
            app.filter_changed()
            assert len(app.visible) == 1
            print("Graph UI smoke passed: three geometries/panel states, rendering, category filters and offline preservation.")
        finally:
            test.cleanup_ui()
            test.temp.cleanup()


if __name__ == "__main__":
    main()
