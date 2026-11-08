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

    # --- yeni özellikler ---

    def _check_column(self, name):
        if name not in self._columns:
            raise KeyError(name)

    def rename_column(self, old, new):
        self._check_column(old)
        if new in self._columns and new != old:
            raise ValueError(f"sütun zaten var: {new}")
        self._columns = [new if c == old else c for c in self._columns]
        self._rows = [{(new if k == old else k): v for k, v in r.items()} for r in self._rows]

    def select(self, title, columns):
        for c in columns:
            self._check_column(c)
        out = Report(title)
        out._columns = list(columns)
        out._rows = [{c: r[c] for c in columns} for r in self._rows]
        return out

    def column(self, name):
        self._check_column(name)
        return [r[name] for r in self._rows]

    def aggregate(self, name):
        values = self.column(name)
        if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            return sum(values)
        if not values:
            return 0
        if all(isinstance(v, str) for v in values):
            return " ".join(v for v in values if v != "")
        raise ValueError(f"sütun karışık: {name}")

    def sort_by(self, name, reverse=False):
        self._check_column(name)
        out = Report(self.title)
        out._columns = list(self._columns)
        out._rows = sorted((dict(r) for r in self._rows), key=lambda r: r[name], reverse=reverse)
        return out

    def to_csv(self):
        def cell(value):
            text = value if isinstance(value, str) else str(value)
            if '"' in text or "," in text:
                return '"' + text.replace('"', '""') + '"'
            return text

        if not self._columns:
            return ""
        lines = [",".join(cell(c) for c in self._columns)]
        for row in self._rows:
            lines.append(",".join(cell(row[c]) for c in self._columns))
        return "\n".join(lines) + "\n"
