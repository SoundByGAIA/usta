class Job:
    def __init__(self, job_id, tries, status="PENDING"):
        self.id = job_id
        self.tries = tries
        self.status = status

    def __repr__(self):
        return f"Job(id={self.id!r}, tries={self.tries!r}, status={self.status!r})"


class Scheduler:
    def __init__(self):
        self._jobs = []

    def add(self, job):
        self._jobs.append(job)

    def failed(self):
        return [j for j in self._jobs if j.status == "FAILED"]
