class BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self) -> (int, bool):
        if self.pos >= len(self.data) * 8:
            return 0, False
        
        byte_index = self.pos // 8
        bit_index_in_byte = self.pos % 8
        
        byte = self.data[byte_index]
        bit = (byte >> (7 - bit_index_in_byte)) & 1
        
        self.pos += 1
        return bit, True

    def read2(self) -> (int, int, bool):
        bit1, ok1 = self.read()
        if not ok1:
            return 0, 0, False
        
        bit2, ok2 = self.read()
        if not ok2:
            return 0, 0, False
            
        return bit1, bit2, True

    def read_n(self, n: int) -> (int, bool):
        if not (0 < n <= 32):
            return 0, False

        if self.pos + n > len(self.data) * 8:
            return 0, False

        value = 0
        for _ in range(n):
            bit, _ = self.read()
            value = (value << 1) | bit
            
        return value, True

    def get_pos(self) -> int:
        return self.pos

    def set_pos(self, n: int) -> bool:
        if not (0 <= n <= len(self.data) * 8):
            return False
        self.pos = n
        return True

    def rewind(self, n: int) -> bool:
        if not (0 <= self.pos - n):
            return False
        self.pos -= n
        return True

    def string_before(self) -> str:
        old_pos = self.pos
        self.rewind(old_pos)
        result = []
        for _ in range(old_pos):
            bit, _ = self.read()
            result.append(str(bit))
        self.pos = old_pos
        return "".join(result)

    def string_after(self) -> str:
        old_pos = self.pos
        result = []
        for _ in range(self.pos, len(self.data) * 8):
            bit, _ = self.read()
            result.append(str(bit))
        self.pos = old_pos
        return "".join(result)

    def full_string(self) -> str:
        old_pos = self.pos
        self.set_pos(0)
        result = []
        for _ in range(len(self.data) * 8):
            bit, _ = self.read()
            result.append(str(bit))
        self.pos = old_pos
        return "".join(result)

    def __len__(self):
        return len(self.data) * 8
