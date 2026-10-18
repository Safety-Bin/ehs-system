"""Public demo workflows: existing data survives, examples do not duplicate."""
import sys
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"
sys.path.insert(0, str(APP.parent))


class DemoWorkflowTests(unittest.TestCase):
    def new_app(self):
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_all_five_populated_examples_render_and_save(self):
        app = self.new_app()
        sites = app.session_state["sites"]
        self.assertEqual(len(sites), 5)
        for uid in list(sites):
            app.selectbox(key="site_selector").set_value(uid).run()
            self.assertEqual(len(app.exception), 0)
            self.assertGreater(app.session_state["sites"][uid]["headcount"], 0)
            submit = next(button for button in app.button if button.label == "제원 저장하고 검토에 반영")
            submit.click().run()
            self.assertEqual(len(app.exception), 0)
            saved = app.session_state["sites"][uid]
            self.assertTrue(saved["demo_is_example"])
            self.assertTrue(saved["buildings"])
            self.assertTrue(saved["equipment"])

    def test_add_missing_examples_preserves_user_data_and_existing_edits(self):
        app = self.new_app()
        sites = app.session_state["sites"]
        keep = next(iter(sites))
        kept = dict(sites[keep], name="수정한 예제 이름", headcount=321)
        actual = dict(kept, uid="user-site", demo_is_example=False, demo_id="", name="사용자 사업장")
        app.session_state["sites"] = {keep: kept, "user-site": actual}
        app.run()
        app.button(key="add_demo_profiles").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.session_state["sites"]), 6)
        self.assertEqual(app.session_state["sites"][keep]["headcount"], 321)
        self.assertEqual(app.session_state["sites"][keep]["name"], "수정한 예제 이름")
        self.assertEqual(app.session_state["sites"]["user-site"]["name"], "사용자 사업장")
        app.button(key="add_demo_profiles").click().run()
        self.assertEqual(len(app.session_state["sites"]), 6)
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
