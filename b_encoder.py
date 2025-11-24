from bl4_decoder_py.b4s.serial.from_string import from_string
from bl4_decoder_py.b4s.serial.serialize import serialize
from bl4_decoder_py.b4s.b85.encode import encode

def encode_to_base85(decoded_str: str, new_level: int = -1) -> (str, str):
    """
    Encodes a human-readable string of decoded parts back into a Base85 serial.
    Returns a tuple of (encoded_serial, error_message).
    """
    if not decoded_str:
        return "", "Decoded string cannot be empty."

    try:
        blocks = from_string(decoded_str)
        
        # If a new level is provided, update the relevant block
        if new_level != -1:
            # The level is the 4th block in the sequence (index 3)
            if len(blocks) > 3:
                blocks[3].value = new_level
            else:
                return "", "Invalid block structure for level update."

        serialized_data = serialize(blocks)
        encoded_serial = encode(serialized_data)
        return encoded_serial, ""
    except Exception as e:
        return "", f"Failed to encode: {e}"
