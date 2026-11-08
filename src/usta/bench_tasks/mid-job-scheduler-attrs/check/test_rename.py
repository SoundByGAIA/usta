import inspect
import unittest

import execute
import model
import report
import scheduler
import summary


def _job(jid, attempt, status="FAILED"):
    return scheduler.Job(jid, attempt, status)


class T(unittest.TestCase):
    def test_job_attrs(self):
        j = _job(1, 2, "OK")
        self.assertEqual((j.job_id, j.attempt, j.status), (1, 2, "OK"))
        self.assertFalse(hasattr(j, "id"))
        self.assertFalse(hasattr(j, "tries"))

    def test_scheduler_uses_new_attrs(self):
        s = scheduler.Scheduler()
        s.add(_job(1, 0, "PENDING"))
        s.add(_job(2, 1))
        self.assertEqual([j.job_id for j in s.failed()], [2])

    def test_report_signature(self):
        self.assertEqual(list(inspect.signature(report.failures).parameters), ["jobs", "attempt"])

    def test_report(self):
        jobs = [_job(1, 2), _job(2, 1), _job(3, 3, "OK"), _job(4, 0)]
        self.assertEqual(report.failures(jobs, 2), [1, 3])
        self.assertEqual(report.failures(jobs, 0), [1, 2, 3, 4])
        self.assertEqual(report.failures([], 1), [])

    def test_summary(self):
        self.assertEqual(
            list(inspect.signature(summary.summary).parameters), ["jobs", "min_attempt"]
        )
        jobs = [_job(1, 1), _job(2, 5), _job(3, 0, "OK"), _job(4, 0)]
        self.assertEqual(summary.summary(jobs, 3), {"total": 4, "ready": 2})
        self.assertEqual(summary.summary([], 1), {"total": 0, "ready": 0})

    def test_retry_delay(self):
        self.assertEqual([execute.retry_delay(n) for n in (1, 2, 3, 4)], [1, 4, 9, 16])

    def test_model_untouched(self):
        m = model.Job(5, 6, "FAILED")
        self.assertEqual((m.job_id, m.attempt), (5, 6))
