from bl4_decoder_py.b4s.serial_datatypes.part.write import write as write_part
from bl4_decoder_py.b4s.serial_datatypes.varbit.write import write as write_varbit
from bl4_decoder_py.b4s.serial_datatypes.varint.write import write as write_varint
from bl4_decoder_py.b4s.serial_datatypes.b4string.write import write_b4string
from bl4_decoder_py.b4s.serial_tokenizer.tokenizer import Token
from bl4_decoder_py.lib.bit.writer import Writer
from bl4_decoder_py.b4s.serial.block import Block

def serialize(s: list[Block]) -> bytearray:
    bw = Writer()
    bw.write_bits(0, 0, 1, 0, 0, 0, 0)
    for block in s:
        if block.token == Token.TOK_SEP1:
            bw.write_bits(0, 0)
        elif block.token == Token.TOK_SEP2:
            bw.write_bits(0, 1)
        elif block.token == Token.TOK_VARINT:
            bw.write_bits(1, 0, 0)
            write_varint(bw, block.value)
        elif block.token == Token.TOK_VARBIT:
            bw.write_bits(1, 1, 0)
            write_varbit(bw, block.value)
        elif block.token == Token.TOK_PART:
            bw.write_bits(1, 0, 1)
            write_part(bw, block.part)
        elif block.token == Token.TOK_STRING:
            bw.write_bits(1, 1, 1)
            write_b4string(bw, block.value_str)
            
    return bw.get_data()
