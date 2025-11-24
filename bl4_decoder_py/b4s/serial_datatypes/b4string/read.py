from bl4_decoder_py.b4s.serial_datatypes.varint.read import read_varint
from bl4_decoder_py.lib.bit.reader import BitReader
from bl4_decoder_py.lib.byte_mirror import UINT7_MIRROR

def read_b4string(br: BitReader) -> str:
    try:
        length = read_varint(br)
    except Exception as e:
        raise IOError("Failed to read b4string length as varint") from e

    str_bytes = bytearray(length)
    for i in range(length):
        raw_char_bits, ok = br.read_n(7)
        if not ok:
            raise EOFError("Unexpected end of data while reading b4string character")
        str_bytes[i] = UINT7_MIRROR[raw_char_bits]
    
    return str_bytes.decode('utf-8')
