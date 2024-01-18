class CustomError(Exception):
    def __init__(self, msg: str):
        self.msg = msg
        super().__init__(self.msg)

    def __str__(self):
        return self.msg


class MsgHandler:
    name: str

    def __init__(self, name: str):
        self.name = name

    def show_msg(self, msg: str):
        print(f"{self.name}: {msg}")

    def show_error(self, error: CustomError):
        print(f"{self.name}: {error}")
