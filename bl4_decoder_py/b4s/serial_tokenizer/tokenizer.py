from enum import Enum
from bl4_decoder_py.lib.bit.reader import BitReader

class Token(Enum):
    TOK_SEP1 = 0            # "00" hard separator (terminator?)
    TOK_SEP2 = 1            # "01" soft separator
    TOK_VARINT = 2          # "100" ... nibble varint
    TOK_VARBIT = 3          # "110" ... varbit
    TOK_PART = 4            # "101" ... complex part block
    TOK_STRING = 5          # "111" is just a b4string after all

class Tokenizer:
    def __init__(self, data: bytes):
        self.br = BitReader(data)
        self.split_positions = []

    def done_string(self) -> str:
        splitted = self.br.full_string()
        for pos in sorted(self.split_positions, reverse=True):
            splitted = splitted[:pos] + "  " + splitted[pos:]
        return splitted

    def bit_reader(self) -> BitReader:
        return self.br

    def next_token(self) -> Token:
        self.split_positions.append(self.br.get_pos())

        b1, b2, ok = self.br.read2()
        if not ok:
            raise EOFError("End of stream while reading token")

        tok = (b1 << 1) | b2
        if tok == 0b00:
            return Token.TOK_SEP1
        if tok == 0b01:
            return Token.TOK_SEP2

        b3, ok = self.br.read()
        if not ok:
            raise EOFError("End of stream while reading token")
        
        tok = (tok << 1) | b3
        
        if tok == 0b100:
            return Token.TOK_VARINT
        if tok == 0b110:
            return Token.TOK_VARBIT
        if tok == 0b101:
            return Token.TOK_PART
        if tok == 0b111:
            return Token.TOK_STRING
            
        self.br.rewind(3)
        raise ValueError(f"Invalid token {tok:03b} at position {self.br.get_pos()}")

    def expect(self, msg: str, *bits: int):
        for bit in bits:
            b, ok = self.br.read()
            if not ok:
                raise EOFError("Unexpected end of data")
            if b != bit:
                raise ValueError(f"{msg} => expected bit {bit}, got {b}")
