class TodoList:
    def __init__(self):
        self.items = []

    def add(self, title):
        self.items.append({"title": title, "done": False})
        return len(self.items) - 1

    def titles(self):
        return [i["title"] for i in self.items]
