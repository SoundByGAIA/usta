import unittest

from scheduler import Job
from summary import summary


class T(unittest.TestCase):
    def test_summary(self):
        jobs = [Job(1, 1, "FAILED"), Job(2, 5, "FAILED"), Job(3, 0, "OK")]
        self.assertEqual(summary(jobs, 3), {"total": 3, "ready": 1})
