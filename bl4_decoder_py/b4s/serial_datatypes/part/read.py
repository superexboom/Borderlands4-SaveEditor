from bl4_decoder_py.b4s.serial_datatypes.part.part import Part, PartSubType
from bl4_decoder_py.b4s.serial_datatypes.varbit.read import read_varbit
from bl4_decoder_py.b4s.serial_datatypes.varint.read import read_varint
from bl4_decoder_py.b4s.serial_tokenizer.tokenizer import Tokenizer, Token

def read_part(t: Tokenizer) -> Part:
    br = t.bit_reader()
    p = Part()

    # First, read the index
    p.index = read_varint(br)

    # Next flag partially determines the type of part
    flag_type1, ok = br.read()
    if not ok:
        raise IOError("Unexpected end of data while reading part flag type 1")

    if flag_type1 == 1:
        p.sub_type = PartSubType.SUBTYPE_INT
        p.value = read_varint(br)
        t.expect("type part, subpart of type int, expect 0x000 as terminator", 0, 0, 0)
        return p

    # If we are here, we're at 0x0
    # The rest of the decoding depends on the next two bits
    flag_type2, ok = br.read_n(2)
    if not ok:
        raise IOError("Unexpected end of data while reading part flag type 2")

    if flag_type2 == 0b10:
        # No data, end of part
        return p
    elif flag_type2 == 0b01:
        # List of varints
        p.sub_type = PartSubType.SUBTYPE_LIST
        
        token = t.next_token()
        if token != Token.TOK_SEP2:
            raise ValueError(f"Expected part list beginning token to be TOK_SEP2, got {token}")

        while True:
            token = t.next_token()

            if token == Token.TOK_SEP1:
                return p
            elif token == Token.TOK_VARINT:
                p.values.append(read_varint(br))
            elif token == Token.TOK_VARBIT:
                p.values.append(read_varbit(br))
            else:
                raise ValueError(f"Unexpected token {token} while reading part list item")

    raise ValueError(f"ERROR: unknown part flagType2 {flag_type2:02b}")
