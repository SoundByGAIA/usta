class Job:
    def __init__(self, job_id, attempt, status="PENDING"):
        self.job_id = job_id
        self.attempt = attempt
        self.status = status

    def __repr__(self):
        return f"Job(job_id={self.job_id!r}, attempt={self.attempt!r}, status={self.status!r})"


class Scheduler:
    def __init__(self):
        self._jobs = []

    def add(self, job):
        self._jobs.append(job)

    def failed(self):
        return [j for j in self._jobs if j.status == "FAILED"]
