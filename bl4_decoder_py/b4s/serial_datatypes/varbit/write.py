from bl4_decoder_py.lib.bit.writer import Writer
from bl4_decoder_py.lib.int_bits_size import int_bits_size
from bl4_decoder_py.b4s.serial_datatypes.varbit.read import VARBIT_LENGTH_BLOCK_SIZE

def write(bw: Writer, value: int):
    n_bits = int_bits_size(value, 0, (1 << VARBIT_LENGTH_BLOCK_SIZE) - 1)

    length_bits = n_bits
    for _ in range(VARBIT_LENGTH_BLOCK_SIZE):
        bw.write_bit(length_bits & 0b1)
        length_bits >>= 1

    for i in range(n_bits):
        bw.write_bit((value >> i) & 0b1)
