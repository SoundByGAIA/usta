def failures(jobs, attempt):
    """En az `attempt` deneme yapmış işlerin kimlikleri, geliş sırasıyla."""
    return [j.job_id for j in jobs if j.attempt >= attempt]
