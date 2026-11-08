class Job:
    """job_id: iş kimliği; attempt: şimdiye kadar yapılan deneme sayısı; status: durum adı."""

    def __init__(self, job_id, attempt, status):
        self.job_id = job_id
        self.attempt = attempt
        self.status = status

    def __repr__(self):
        return f"Job(job_id={self.job_id!r}, attempt={self.attempt!r}, status={self.status!r})"
