from bl4_decoder_py.lib.bit.reader import BitReader
from bl4_decoder_py.lib.byte_mirror import UINT4_MIRROR

VARINT_NB_BLOCKS = 4
VARINT_BITS_PER_BLOCK = 4

def read_varint(br: BitReader) -> int:
    data_read = 0
    output = 0
    
    for _ in range(VARINT_NB_BLOCKS):
        # Read standard block
        block32, ok = br.read_n(VARINT_BITS_PER_BLOCK)
        if not ok:
            raise IOError("Unexpected end of data while reading varint")
        
        output |= UINT4_MIRROR[block32] << data_read
        data_read += VARINT_BITS_PER_BLOCK
        
        # Continuation bit
        cont, ok = br.read()
        if not ok:
            raise IOError("Unexpected end of data while reading varint continuation bit")
            
        if cont == 0:
            break
            
    return output
