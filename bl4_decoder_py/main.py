import sys
import re
from bl4_decoder_py.b4s.b85.decode import decode
from bl4_decoder_py.b4s.b85.encode import encode
from bl4_decoder_py.b4s.serial.deserialize import deserialize
from bl4_decoder_py.b4s.serial.serialize import serialize
from bl4_decoder_py.b4s.serial.from_string import from_string
from bl4_decoder_py.b4s.serial_tokenizer.tokenizer import Token
from bl4_decoder_py.b4s.serial_datatypes.part.part import PartSubType
from bl4_decoder_py.b4s.serial.block import Block


def get_canonical_string(blocks: list[Block]) -> str:
    """Gets the canonical string representation of the blocks, without cosmetic spaces."""
    parts = []
    for block in blocks:
        token = block.token
        if token in [Token.TOK_VARINT, Token.TOK_VARBIT]:
            parts.append(str(block.value))
        elif token == Token.TOK_PART:
            part = block.part
            if part.sub_type == PartSubType.SUBTYPE_NONE:
                parts.append(f"{{{part.index}}}")
            elif part.sub_type == PartSubType.SUBTYPE_INT:
                parts.append(f"{{{part.index}:{part.value}}}")
            elif part.sub_type == PartSubType.SUBTYPE_LIST:
                values_str = ' '.join(map(str, part.values))
                parts.append("{" + f"{part.index}:[{values_str}]" + "}")
        elif token == Token.TOK_STRING:
            escaped_str = block.value_str.replace('\\', '\\\\').replace('"', '\\"')
            parts.append(f'"{escaped_str}"')
        elif token == Token.TOK_SEP1:
            parts.append("|")
        elif token == Token.TOK_SEP2:
            parts.append(",")
    
    # This join will handle cases like "123,456" vs "123, 456" by creating a consistent representation
    return "".join(parts)


def format_blocks(blocks: list[Block]) -> str:
    """Formats the deserialized blocks into a human-readable string format."""
    output_parts = []
    for i, block in enumerate(blocks):
        token = block.token
        
        current_part = ""
        is_data_block = False

        if token in [Token.TOK_VARINT, Token.TOK_VARBIT]:
            current_part = str(block.value)
            is_data_block = True
        elif token == Token.TOK_PART:
            part = block.part
            if part.sub_type == PartSubType.SUBTYPE_NONE:
                current_part = f"{{{part.index}}}"
            elif part.sub_type == PartSubType.SUBTYPE_INT:
                current_part = f"{{{part.index}:{part.value}}}"
            elif part.sub_type == PartSubType.SUBTYPE_LIST:
                values_str = ' '.join(map(str, part.values))
                current_part = "{" + f"{part.index}:[{values_str}]" + "}"
            is_data_block = True
        elif token == Token.TOK_STRING:
            escaped_str = block.value_str.replace('\\', '\\\\').replace('"', '\\"')
            current_part = f'"{escaped_str}"'
            is_data_block = True
        elif token == Token.TOK_SEP1:
            current_part = "|"
        elif token == Token.TOK_SEP2:
            current_part = ","
        
        output_parts.append(current_part)

        # Add space logic
        if i + 1 < len(blocks):
            next_block = blocks[i+1]
            # Add a space if current block is data and next block is also data
            if is_data_block and next_block.token not in [Token.TOK_SEP1, Token.TOK_SEP2]:
                 output_parts.append(" ")
            # Add a space after a comma separator
            elif token == Token.TOK_SEP2:
                output_parts.append(" ")
            # Add a space after a pipe unless it's followed by another pipe
            elif token == Token.TOK_SEP1 and next_block.token != Token.TOK_SEP1:
                 output_parts.append(" ")

    return "".join(output_parts)

def main():
    if len(sys.argv) > 1:
        serial_input = sys.argv[1]
    else:
        serial_input = input("请输入 Borderlands 4 物品序列号: ")

    try:
        if serial_input.startswith("@U"):
            decoded_data = decode(serial_input)
            blocks, _, err = deserialize(decoded_data)
            if err:
                raise err
            
            formatted_string = format_blocks(blocks)
            print(f"Formatted: {formatted_string}")

            serialized_data = serialize(blocks)
            reconstructed_serial = encode(serialized_data)
            print(f"Reconstructed: {reconstructed_serial}")
        else:
            blocks = from_string(serial_input)
            serialized_data = serialize(blocks)
            encoded_serial = encode(serialized_data)
            print(f"Encoded: {encoded_serial}")

    except (ValueError, IOError, EOFError) as e:
        print(f"\n错误: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
