import re
from bl4_decoder_py.b4s.serial.block import Block
from bl4_decoder_py.b4s.serial_datatypes.part.part import Part, PartSubType
from bl4_decoder_py.b4s.serial_tokenizer.tokenizer import Token
from bl4_decoder_py.lib.bit.writer import Writer
from bl4_decoder_py.b4s.serial_datatypes.varint.write import write as write_varint
from bl4_decoder_py.b4s.serial_datatypes.varbit.write import write as write_varbit

def is_numbers(s: str) -> (int, bool):
    s = s.strip()
    if not s.isdigit():
        return 0, False
    return int(s), True

def is_part_simple(s: str) -> (int, bool):
    s = s.strip()
    if not s.startswith('{') or not s.endswith('}'):
        return 0, False
    return is_numbers(s[1:-1])

def is_part_subtype_int(s: str) -> (int, int, bool):
    s = s.strip()
    if not s.startswith('{') or not s.endswith('}'):
        return 0, 0, False
    
    middle = s[1:-1].strip()
    parts = middle.split(':')
    if len(parts) != 2:
        return 0, 0, False
        
    index, ok = is_numbers(parts[0])
    if not ok:
        return 0, 0, False
    
    value, ok = is_numbers(parts[1])
    if not ok:
        return 0, 0, False
        
    return index, value, True

def is_part_subtype_list(s: str) -> (int, list[int], bool):
    s = s.strip()
    if not s.startswith('{') or not s.endswith('}'):
        return 0, None, False
        
    middle = s[1:-1].strip()
    parts = middle.split(':')
    if len(parts) < 2:
        return 0, None, False
        
    index, ok = is_numbers(parts[0])
    if not ok:
        return 0, None, False
        
    list_str = parts[1].strip()
    if not list_str.startswith('[') or not list_str.endswith(']'):
        return 0, None, False
        
    list_str = list_str[1:-1].strip()
    
    values = []
    for num_str in re.split(r'[\s,]+', list_str):
        if not num_str:
            continue
        v, ok = is_numbers(num_str)
        if not ok:
            return 0, None, False
        values.append(v)
        
    return index, values, True

def best_type_for_value(v: int) -> Token:
    bw_varint = Writer()
    write_varint(bw_varint, v)

    bw_varbit = Writer()
    write_varbit(bw_varbit, v)

    if bw_varint.get_pos() > bw_varbit.get_pos():
        return Token.TOK_VARBIT
    else:
        return Token.TOK_VARINT

def from_string(s: str) -> list[Block]:
    blocks = []
    i = 0
    while i < len(s):
        char = s[i]

        if char.isspace():
            i += 1
            continue
        
        if char == '|':
            blocks.append(Block(Token.TOK_SEP1))
            i += 1
            continue

        if char == ',':
            blocks.append(Block(Token.TOK_SEP2))
            i += 1
            continue

        if char.isdigit():
            start = i
            while i < len(s) and s[i].isdigit():
                i += 1
            num_str = s[start:i]
            val, _ = is_numbers(num_str)
            block = Block(best_type_for_value(val))
            block.value = val
            blocks.append(block)
            continue
            
        if char == '{':
            end = s.find('}', i)
            if end == -1:
                raise ValueError(f"Unmatched '{{' at position {i}")
            
            part_str = s[i : end+1]
            i = end + 1

            index, values, ok = is_part_subtype_list(part_str)
            if ok:
                part = Part()
                part.index, part.sub_type, part.values = index, PartSubType.SUBTYPE_LIST, values
                block = Block(Token.TOK_PART)
                block.part = part
                blocks.append(block)
                continue

            index, value, ok = is_part_subtype_int(part_str)
            if ok:
                part = Part()
                part.index, part.sub_type, part.value = index, PartSubType.SUBTYPE_INT, value
                block = Block(Token.TOK_PART)
                block.part = part
                blocks.append(block)
                continue

            value, ok = is_part_simple(part_str)
            if ok:
                part = Part()
                part.index, part.sub_type = value, PartSubType.SUBTYPE_NONE
                block = Block(Token.TOK_PART)
                block.part = part
                blocks.append(block)
                continue
                
            raise ValueError(f"Invalid part format: '{part_str}'")

        if char == '"':
            end = i + 1
            while end < len(s):
                if s[end] == '"':
                    # Look behind for escape character
                    if s[end-1] != '\\':
                        break
                end += 1

            if end >= len(s):
                raise ValueError(f"Unmatched '\"' at position {i}")

            str_content = s[i+1:end]
            i = end + 1

            # Unescape
            str_content = str_content.replace('\\"', '"').replace('\\\\', '\\')

            block = Block(Token.TOK_STRING)
            block.value_str = str_content
            blocks.append(block)
            continue

        raise ValueError(f"Invalid character: '{char}' at position {i}")

    return blocks
