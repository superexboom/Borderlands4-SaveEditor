from bl4_decoder_py.lib.bit.writer import Writer
from bl4_decoder_py.b4s.serial_datatypes.varint.write import write as write_varint
from bl4_decoder_py.b4s.serial_datatypes.varbit.write import write as write_varbit
from bl4_decoder_py.b4s.serial_datatypes.part.part import Part, PartSubType

def best_type_for_value(v: int) -> (tuple[int, ...], tuple[int, ...]):
    bw_varint = Writer()
    write_varint(bw_varint, v)

    bw_varbit = Writer()
    write_varbit(bw_varbit, v)

    if bw_varint.get_pos() > bw_varbit.get_pos():
        return (1, 1, 0), bw_varbit.get_bits()
    else:
        return (1, 0, 0), bw_varint.get_bits()

def write(bw: Writer, p: Part):
    write_varint(bw, p.index)

    if p.sub_type == PartSubType.SUBTYPE_NONE:
        bw.write_bits(0, 1, 0)
    elif p.sub_type == PartSubType.SUBTYPE_INT:
        bw.write_bit(1)
        write_varint(bw, p.value)
        bw.write_bits(0, 0, 0)
    elif p.sub_type == PartSubType.SUBTYPE_LIST:
        bw.write_bits(0, 0, 1)
        bw.write_bits(0, 1)

        for v in p.values:
            type_bits, value_bits = best_type_for_value(v)
            bw.write_bits(*type_bits)
            bw.write_bits(*value_bits)

        bw.write_bits(0, 0)
