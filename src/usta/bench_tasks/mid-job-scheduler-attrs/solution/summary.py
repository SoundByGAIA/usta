def summary(jobs, min_attempt):
    total = len(jobs)
    ready = sum(1 for j in jobs if j.status == "FAILED" and j.attempt < min_attempt)
    return {"total": total, "ready": ready}
