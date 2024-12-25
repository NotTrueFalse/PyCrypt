class Sector:
    def __init__(self, number: int, data: bytes):
        self.number = number
        self.data = data

    def __repr__(self):
        return f"<Sector {self.number}>"

    def __str__(self):
        return f"<Sector {self.number}>"

    def __bytes__(self):
        return self.data