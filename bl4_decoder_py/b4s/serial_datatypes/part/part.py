from enum import Enum

class PartSubType(Enum):
    SUBTYPE_NONE = 0
    SUBTYPE_INT = 1
    SUBTYPE_LIST = 2

class Part:
    def __init__(self):
        self.index: int = 0
        self.sub_type: PartSubType = PartSubType.SUBTYPE_NONE
        self.value: int = 0
        self.values: list[int] = []
