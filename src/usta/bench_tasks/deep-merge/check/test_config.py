import copy
import unittest

from config import deep_merge


class T(unittest.TestCase):
    def test_nested_merge_and_replace(self):
        base = {"a": 1, "b": {"x": 1, "y": 2}, "l": [1, 2]}
        out = deep_merge(base, {"b": {"y": 3, "z": 4}, "l": [9], "c": 5})
        self.assertEqual(out, {"a": 1, "b": {"x": 1, "y": 3, "z": 4}, "l": [9], "c": 5})

    def test_none_deletes_nested_and_top(self):
        out = deep_merge({"a": 1, "b": {"x": 1, "y": 2}}, {"a": None, "b": {"x": None}})
        self.assertEqual(out, {"b": {"y": 2}})

    def test_none_for_missing_key_is_ignored(self):
        self.assertEqual(deep_merge({"a": 1}, {"zz": None}), {"a": 1})

    def test_dict_replaces_non_dict_and_vice_versa(self):
        self.assertEqual(deep_merge({"a": 1}, {"a": {"k": 1}}), {"a": {"k": 1}})
        self.assertEqual(deep_merge({"a": {"k": 1}}, {"a": 2}), {"a": 2})

    def test_inputs_not_mutated_and_no_shared_objects(self):
        base = {"b": {"x": [1]}}
        over = {"c": {"y": [2]}}
        snap = (copy.deepcopy(base), copy.deepcopy(over))
        out = deep_merge(base, over)
        out["b"]["x"].append(99)
        out["c"]["y"].append(99)
        self.assertEqual((base, over), snap)
