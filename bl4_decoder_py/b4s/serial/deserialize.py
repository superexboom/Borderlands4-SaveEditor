import io
from bl4_decoder_py.b4s.serial.block import Block
from bl4_decoder_py.b4s.serial_datatypes.part.read import read_part
from bl4_decoder_py.b4s.serial_datatypes.varbit.read import read_varbit
from bl4_decoder_py.b4s.serial_datatypes.varint.read import read_varint
from bl4_decoder_py.b4s.serial_datatypes.b4string.read import read_b4string
from bl4_decoder_py.b4s.serial_tokenizer.tokenizer import Tokenizer, Token

def deserialize(data: bytes) -> (list[Block], str):
    t = Tokenizer(data)

    # Expect the magic header as the first bits
    try:
        t.expect("magic header", 0, 0, 1, 0, 0, 0, 0)
    except (IOError, EOFError) as e:
        return [], t.done_string(), e

    br = t.bit_reader()
    blocks = []
    trailing_terminators = 0

    while True:
        try:
            token = t.next_token()
        except EOFError:
            break
        except (IOError, ValueError) as e:
            return [], t.done_string(), e
            
        block = Block(token)

        if token == Token.TOK_SEP1:
            trailing_terminators += 1
        else:
            trailing_terminators = 0

        if token == Token.TOK_VARINT:
            block.value = read_varint(br)
        elif token == Token.TOK_VARBIT:
            block.value = read_varbit(br)
        elif token == Token.TOK_PART:
            block.part = read_part(t)
        elif token == Token.TOK_STRING:
            block.value_str = read_b4string(br)
        
        blocks.append(block)

    # Sanitization: we probably read the zero-padding as terminators.
    # Only one terminator is needed, remove the extra ones
    if trailing_terminators > 1:
        blocks = blocks[:-(trailing_terminators - 1)]

    return blocks, t.done_string(), None
