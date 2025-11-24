from bl4_decoder_py.lib.bit.writer import Writer

VARINT_BITS_PER_BLOCK = 4
VARINT_MAX_USABLE_BITS = 16

def write(bw: Writer, value: int):
    n_bits = 0
    if value > 0:
        n_bits = value.bit_length()
    else:
        n_bits = 1

    if n_bits > VARINT_MAX_USABLE_BITS:
        n_bits = VARINT_MAX_USABLE_BITS

    while n_bits > VARINT_BITS_PER_BLOCK:
        for _ in range(VARINT_BITS_PER_BLOCK):
            bw.write_bit(value & 0b1)
            value >>= 1
            n_bits -= 1
        bw.write_bit(1)

    if n_bits > 0:
        for i in range(VARINT_BITS_PER_BLOCK):
            if n_bits > 0:
                bw.write_bit(value & 0b1)
                value >>= 1
                n_bits -= 1
            else:
                bw.write_bit(0)
        bw.write_bit(0)
