class Writer:
    def __init__(self):
        self.data = bytearray()
        self.pos = 0

    def write_bit(self, bit: int):
        byte_index = self.pos // 8
        bit_index_in_byte = 7 - (self.pos % 8)

        while byte_index >= len(self.data):
            self.data.append(0)

        if bit & 1:
            self.data[byte_index] |= (1 << bit_index_in_byte)
        else:
            self.data[byte_index] &= ~(1 << bit_index_in_byte)

        self.pos += 1

    def write_bits(self, *bits: int):
        for bit in bits:
            self.write_bit(bit)

    def write_n(self, value: int, n: int):
        for i in range(n - 1, -1, -1):
            bit = (value >> i) & 1
            self.write_bit(bit)

    def get_data(self) -> bytearray:
        return self.data

    def get_pos(self) -> int:
        return self.pos

    def get_bits(self) -> tuple[int, ...]:
        bits = []
        for i in range(self.pos):
            byte_index = i // 8
            bit_index_in_byte = 7 - (i % 8)
            bit = (self.data[byte_index] >> bit_index_in_byte) & 1
            bits.append(bit)
        return tuple(bits)

    def __str__(self):
        s = ""
        for i in range(self.pos):
            byte_index = i // 8
            bit_index = 7 - (i % 8)
            if (self.data[byte_index] >> bit_index) & 1:
                s += "1"
            else:
                s += "0"
        return s
