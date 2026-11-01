import json


class TodoList:
    def __init__(self):
        self.items = []

    def add(self, title):
        self.items.append({"title": title, "done": False})
        return len(self.items) - 1

    def titles(self):
        return [i["title"] for i in self.items]

    def complete(self, index):
        if not 0 <= index < len(self.items):
            raise IndexError(index)
        if self.items[index]["done"]:
            raise ValueError("zaten tamamlandı")
        self.items[index]["done"] = True

    def pending(self):
        return [i["title"] for i in self.items if not i["done"]]

    def to_json(self):
        return json.dumps(self.items)

    @classmethod
    def from_json(cls, text):
        t = cls()
        t.items = json.loads(text)
        return t
