import unittest

import api
import greeting
import report
import users


class T(unittest.TestCase):
    def test_display_name_strips(self):
        self.assertEqual(users.display_name({"name": "  Ayşe "}), "Ayşe")

    def test_old_name_gone(self):
        self.assertFalse(hasattr(users, "get_user_name"))
        for mod in (api, greeting, report):
            self.assertFalse(hasattr(mod, "get_user_name"))

    def test_callers_updated(self):
        self.assertEqual(greeting.greet({"name": " Can "}), "Merhaba, Can!")
        self.assertEqual(report.names([{"name": "b "}, {"name": " a"}]), ["a", "b"])
        self.assertEqual(api.serialize({"id": 7, "name": " Zeynep"}), {"id": 7, "name": "Zeynep"})
