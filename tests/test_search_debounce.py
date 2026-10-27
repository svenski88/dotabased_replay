from types import SimpleNamespace
import unittest

from app import ReplayApp


class Scheduler:
    def __init__(self):
        self.callbacks = {}
        self.next_id = 0

    def after(self, milliseconds, callback):
        self.next_id += 1
        self.callbacks[self.next_id] = (milliseconds, callback)
        return self.next_id

    def after_cancel(self, timer):
        self.callbacks.pop(timer)


class DebounceTests(unittest.TestCase):
    def test_typing_burst_schedules_one_render_and_explicit_cancel_clears_it(self):
        renders = []
        app = SimpleNamespace(root=Scheduler(), search_timer=None, render_matches=lambda: renders.append(True))
        app.cancel_search_timer = lambda: ReplayApp.cancel_search_timer(app)
        for _ in range(20):
            ReplayApp.search_changed(app)
        self.assertEqual(len(app.root.callbacks), 1)
        delay, callback = next(iter(app.root.callbacks.values()))
        self.assertEqual(delay, 150)
        self.assertEqual(renders, [])
        callback()
        self.assertEqual(renders, [True])
        app.cancel_search_timer()
        self.assertEqual(app.root.callbacks, {})
        self.assertIsNone(app.search_timer)


if __name__ == "__main__":
    unittest.main()
