# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# Add the parent directory of 'bl4_decoder_py' to the system path
# This allows importing modules from it, assuming a standard structure
current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir))

try:
    from bl4_decoder_py.b4s.b85.decode import decode
    from bl4_decoder_py.b4s.b85.encode import encode
    from bl4_decoder_py.b4s.serial.deserialize import deserialize
    from bl4_decoder_py.b4s.serial.serialize import serialize
    from bl4_decoder_py.b4s.serial.from_string import from_string
    from bl4_decoder_py.b4s.serial.block import Block
    from bl4_decoder_py.b4s.serial_tokenizer.tokenizer import Token
    from bl4_decoder_py.b4s.serial_datatypes.part.part import PartSubType
except ImportError as e:
    raise ImportError(
        f"无法从 'bl4_decoder_py' 导入模块。请确保该目录与此脚本位于同一级别。\n错误: {e}"
    )

def _format_blocks(blocks: list[Block]) -> str:
    """
    Formats deserialized blocks into a human-readable string, similar to the
    original main.py in the decoder library.
    Example output: '8, 0, 1, 50| 2, 1570|| {53} {2} ...'
    """
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

        # Add spacing for readability, matching the desired format
        if i + 1 < len(blocks):
            next_block = blocks[i+1]
            if is_data_block and next_block.token not in [Token.TOK_SEP1, Token.TOK_SEP2]:
                 output_parts.append(" ")
            elif token == Token.TOK_SEP2:
                output_parts.append(" ")
            elif token == Token.TOK_SEP1 and next_block.token != Token.TOK_SEP1:
                 output_parts.append(" ")

    return "".join(output_parts)

def decode_serial_to_string(serial_b85: str) -> (str, list, str or None):
    """
    Decodes a Base85 serial string into a human-readable formatted string.
    
    Args:
        serial_b85: The Base85 encoded item serial, starting with '@U'.

    Returns:
        A tuple containing:
        - The formatted string representation of the item data.
        - The raw blocks list from deserialization.
        - An error message string if an error occurs, otherwise None.
    """
    if not serial_b85 or not serial_b85.startswith("@U"):
        return "", [], "无效的序列号: 它必须以'@U'开头。"

    try:
        decoded_data = decode(serial_b85)
        blocks, _, err = deserialize(decoded_data)
        if err:
            return "", [], str(err)
        
        formatted_string = _format_blocks(blocks)
        return formatted_string, blocks, None

    except (ValueError, IOError, EOFError) as e:
        return "", [], f"解码过程中发生错误: {e}"

def encode_string_to_serial(decoded_string: str) -> (str, str or None):
    """
    Encodes a human-readable string back into a Base85 serial.
    
    Args:
        decoded_string: The human-readable string representation of the item.

    Returns:
        A tuple containing:
        - The Base85 encoded serial string.
        - An error message string if an error occurs, otherwise None.
    """
    if not decoded_string:
        return "", "输入字符串不能为空。"
    
    try:
        blocks = from_string(decoded_string)
        serialized_data = serialize(blocks)
        encoded_serial = encode(serialized_data)
        return encoded_serial, None
    except Exception as e:
        return "", f"编码过程中发生错误: {e}"
