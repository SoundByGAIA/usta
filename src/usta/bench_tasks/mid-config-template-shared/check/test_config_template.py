import unittest

import config
import template


class T(unittest.TestCase):
    def test_load_config_does_not_leak(self):
        a = config.load_config({"debug": True})
        self.assertEqual(a["debug"], True)
        self.assertEqual(a["retries"], 2)
        b = config.load_config()
        self.assertEqual(b["debug"], False)
        self.assertEqual(b["retries"], 2)
        self.assertEqual(b["tags"], ["base"])

    def test_default_config_untouched(self):
        config.load_config({"retries": 9, "extra": 1})
        self.assertEqual(config.DEFAULT_CONFIG, {"debug": False, "retries": 2, "tags": ["base"]})

    def test_result_does_not_share_list(self):
        r = config.load_config()
        r["tags"].append("x")
        self.assertEqual(config.DEFAULT_CONFIG["tags"], ["base"])
        self.assertEqual(config.load_config()["tags"], ["base"])

    def test_overrides_list_used(self):
        r = config.load_config({"tags": ["a", "b"]})
        self.assertEqual(r["tags"], ["a", "b"])


class R(unittest.TestCase):
    def test_named_and_repeated(self):
        self.assertEqual(template.render("Merhaba {name}!", {"name": "Ali"}), "Merhaba Ali!")
        self.assertEqual(template.render("{a}{b}", {"a": "1", "b": "2"}), "12")
        self.assertEqual(template.render("{n} {n}", {"n": "x"}), "x x")

    def test_missing_key_empty(self):
        self.assertEqual(template.render("Deg({x})", {}), "Deg()")
        self.assertEqual(template.render("[{a}]", {"b": "z"}), "[]")

    def test_braces_escape(self):
        self.assertEqual(template.render("{{ok}}", {}), "{ok}")
        self.assertEqual(template.render("{{{a}}}", {"a": "v"}), "{v}")
        self.assertEqual(template.render("{{{{", {}), "{{")

    def test_invalid(self):
        for bad in ("a {x", "x} b", "{", "}", "{a}}", "{{}"):
            with self.assertRaises(ValueError, msg=bad):
                template.render(bad, {"a": "1"})

    def test_render_all(self):
        self.assertEqual(template.render_all(["{a}", "{a}-"], {"a": 5}), ["5", "5-"])
        self.assertEqual(template.render_all([], {}), [])
        self.assertEqual(template.render_all(["{y}!"], {}), ["!"])


if __name__ == "__main__":
    unittest.main()
