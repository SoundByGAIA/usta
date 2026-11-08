import unittest

from model import Job as ModelJob
from report import failures
from scheduler import Job, Scheduler


class T(unittest.TestCase):
    def test_model_example(self):
        self.assertEqual(ModelJob(1, 2, "X").attempt, 2)

    def test_scheduler(self):
        s = Scheduler()
        s.add(Job(job_id=1, attempt=0, status="PENDING"))
        s.add(Job(job_id=2, attempt=1, status="FAILED"))
        self.assertEqual([j.job_id for j in s.failed()], [2])

    def test_failures(self):
        jobs = [Job(1, 2, "FAILED"), Job(2, 1, "FAILED"), Job(3, 3, "OK")]
        self.assertEqual(failures(jobs, 2), [1, 3])
