class Report:
    """Basit satır/sütun tablosu. Sütunlar ilk add_row çağrısında kurulur."""

    def __init__(self, title=""):
        self.title = title
        self._columns = []
        self._rows = []

    def add_row(self, values):
        if not self._columns:
            self._columns = list(values.keys())
        row = {c: values.get(c, "") for c in self._columns}
        self._rows.append(row)
        return len(self._rows) - 1

    def clear(self):
        self._rows.clear()

    def row_count(self):
        return len(self._rows)

    def rows(self):
        return [dict(r) for r in self._rows]

    def total(self):
        total = 0
        for row in self._rows:
            for value in row.values():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    total += value
        return total

    def to_dict(self):
        return {
            "title": self.title,
            "columns": list(self._columns),
            "rows": [[r[c] for c in self._columns] for r in self._rows],
        }
