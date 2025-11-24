from bl4_decoder_py.lib.bit.reader import BitReader
from bl4_decoder_py.lib.byte_mirror import UINT5_MIRROR

VARBIT_LENGTH_BLOCK_SIZE = 5

def read_varbit(br: BitReader) -> int:
    length, ok = br.read_n(VARBIT_LENGTH_BLOCK_SIZE)
    if not ok:
        raise IOError("Unexpected end of data while reading varbit length")
    
    length = UINT5_MIRROR[length]

    if length == 0:
        # TODO: A length of 0 is a special case which _might_ mean 32,
        # but the Go code has a commented out section. For now, mirroring the implemented behavior.
        return 0

    v = 0
    for i in range(length):
        bit, ok = br.read()
        if not ok:
            raise IOError("Unexpected end of data while reading varbit value")
        
        v |= bit << i
        
    return v
