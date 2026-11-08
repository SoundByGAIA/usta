def summary(jobs, min_attempts):
    total = len(jobs)
    ready = sum(1 for j in jobs if j.status == "FAILED" and j.tries < min_attempts)
    return {"total": total, "ready": ready}
