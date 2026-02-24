def is_positive_int(value: str) -> bool:
    try:
        return int(value) > 0
    except ValueError:
        return False

def is_valid_tx_id(tx_id: str) -> bool:
    """Basic transaction ID validation"""
    if not tx_id:
        return False
    if len(tx_id) < 6:
        return False
    return True

def is_valid_bingo_number(number: int) -> bool:
    return 1 <= number <= 75

def has_enough_balance(balance: int, price: int) -> bool:
    return balance >= price
