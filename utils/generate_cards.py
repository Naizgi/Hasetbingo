#!/usr/bin/env python3
"""
Generate 400 unique bingo cards - CORRECTED VERSION
"""
import json
import random
import os
from typing import List

def generate_valid_bingo_card() -> List[int]:
    """
    Generate a CORRECT bingo card
    """
    card = []
    
    # Generate each column separately
    # Column B: 1-15 (indices 0, 5, 10, 15, 20)
    b_numbers = random.sample(range(1, 16), 5)
    # Column I: 16-30 (indices 1, 6, 11, 16, 21)
    i_numbers = random.sample(range(16, 31), 5)
    # Column N: 31-45 (indices 2, 7, 12, 17, 22) - center is FREE
    n_numbers = random.sample(range(31, 46), 4)  # Only need 4, center is FREE
    # Column G: 46-60 (indices 3, 8, 13, 18, 23)
    g_numbers = random.sample(range(46, 61), 5)
    # Column O: 61-75 (indices 4, 9, 14, 19, 24)
    o_numbers = random.sample(range(61, 76), 5)
    
    # Build card row by row
    n_index = 0  # Track position in n_numbers
    for row in range(5):
        # Row has 5 columns: B, I, N, G, O
        if row == 2:  # Middle row
            card.append(b_numbers[row])      # B
            card.append(i_numbers[row])      # I
            card.append(0)                   # N - FREE
            card.append(g_numbers[row])      # G
            card.append(o_numbers[row])      # O
        else:
            card.append(b_numbers[row])      # B
            card.append(i_numbers[row])      # I
            card.append(n_numbers[n_index])  # N
            card.append(g_numbers[row])      # G
            card.append(o_numbers[row])      # O
            n_index += 1
    
    return card

def generate_all_cards(count: int = 400) -> List[List[int]]:
    """Generate all unique cards"""
    cards = []
    seen = set()
    attempts = 0
    max_attempts = count * 100
    
    print(f"Generating {count} unique bingo cards...")
    
    while len(cards) < count and attempts < max_attempts:
        attempts += 1
        card = generate_valid_bingo_card()
        
        # Create a unique signature
        card_signature = list(card)
        card_signature[12] = -1  # Replace FREE space
        card_tuple = tuple(card_signature)
        
        if card_tuple not in seen:
            seen.add(card_tuple)
            cards.append(card)
            
            if len(cards) % 50 == 0:
                print(f"  Generated {len(cards)}/{count} cards...")
    
    print(f"Generated {len(cards)} cards in {attempts} attempts")
    return cards

def validate_card(card: List[int]) -> bool:
    """Validate a bingo card"""
    if len(card) != 25:
        return False
    
    # Check center is FREE
    if card[12] != 0:
        print(f"Center not FREE: {card[12]}")
        return False
    
    # Check each column has correct range
    # B column: indices 0, 5, 10, 15, 20
    b_indices = [0, 5, 10, 15, 20]
    for idx in b_indices:
        if idx == 12:  # Skip FREE
            continue
        if not (1 <= card[idx] <= 15):
            print(f"B[{idx}]={card[idx]} not in 1-15")
            return False
    
    # I column: indices 1, 6, 11, 16, 21
    i_indices = [1, 6, 11, 16, 21]
    for idx in i_indices:
        if not (16 <= card[idx] <= 30):
            print(f"I[{idx}]={card[idx]} not in 16-30")
            return False
    
    # N column: indices 2, 7, 12, 17, 22
    n_indices = [2, 7, 12, 17, 22]
    for idx in n_indices:
        if idx == 12:  # FREE space
            continue
        if not (31 <= card[idx] <= 45):
            print(f"N[{idx}]={card[idx]} not in 31-45")
            return False
    
    # G column: indices 3, 8, 13, 18, 23
    g_indices = [3, 8, 13, 18, 23]
    for idx in g_indices:
        if not (46 <= card[idx] <= 60):
            print(f"G[{idx}]={card[idx]} not in 46-60")
            return False
    
    # O column: indices 4, 9, 14, 19, 24
    o_indices = [4, 9, 14, 19, 24]
    for idx in o_indices:
        if not (61 <= card[idx] <= 75):
            print(f"O[{idx}]={card[idx]} not in 61-75")
            return False
    
    return True

def format_card_display(card: List[int]) -> str:
    """Format card for display"""
    headers = ["B", "I", "N", "G", "O"]
    lines = ["   " + "  ".join(headers)]
    lines.append("   " + "-" * 29)
    
    for row in range(5):
        row_cells = []
        for col in range(5):
            idx = row * 5 + col
            num = card[idx]
            
            if idx == 12:
                row_cells.append("FREE")
            else:
                row_cells.append(f"{num:3}")
        
        lines.append("   " + " ".join(row_cells))
    
    return "\n".join(lines)

def verify_card_structure(card: List[int]):
    """Debug: show card structure"""
    print("\n🔍 Card structure analysis:")
    print("Row/Col   B(1-15)  I(16-30)  N(31-45)  G(46-60)  O(61-75)")
    print("-" * 60)
    
    for row in range(5):
        row_text = []
        for col in range(5):
            idx = row * 5 + col
            row_text.append(f"{card[idx]:3}")
        print(f"Row {row}:  " + "      ".join(row_text))
    
    # Check columns
    print("\n📊 Column verification:")
    columns = {
        "B": ([0, 5, 10, 15, 20], (1, 15)),
        "I": ([1, 6, 11, 16, 21], (16, 30)),
        "N": ([2, 7, 12, 17, 22], (31, 45)),
        "G": ([3, 8, 13, 18, 23], (46, 60)),
        "O": ([4, 9, 14, 19, 24], (61, 75))
    }
    
    for col_name, (indices, (low, high)) in columns.items():
        values = []
        for idx in indices:
            if idx == 12:  # FREE space
                values.append("FREE")
            else:
                values.append(card[idx])
        
        # Check if valid (excluding FREE)
        filtered = [v for v in values if v != "FREE"]
        valid = all(low <= v <= high for v in filtered)
        
        print(f"{col_name}: {values} {'✅' if valid else '❌'}")

def main():
    print("=" * 50)
    print("Habesha Bingo - Card Generator (FIXED)")
    print("=" * 50)
    
    # Generate cards
    cards = generate_all_cards(400)
    
    if len(cards) < 400:
        print(f"Warning: Only generated {len(cards)} cards")
        while len(cards) < 400:
            cards.append(generate_valid_bingo_card())
    
    # Test and validate first card
    print("\n🔍 Testing first card...")
    verify_card_structure(cards[0])
    
    # Validate all cards
    valid_count = 0
    invalid_cards = []
    for i, card in enumerate(cards):
        if validate_card(card):
            valid_count += 1
        else:
            invalid_cards.append(i)
            if len(invalid_cards) <= 3:
                print(f"\nCard {i} failed validation")
    
    print(f"\n📊 Validation results:")
    print(f"Valid cards: {valid_count}/{len(cards)}")
    if invalid_cards:
        print(f"Invalid cards: {len(invalid_cards)} (indices: {invalid_cards[:10]}{'...' if len(invalid_cards) > 10 else ''})")
    
    # Check uniqueness
    seen = set()
    duplicates = []
    for i, card in enumerate(cards):
        card_tuple = tuple(card)
        if card_tuple in seen:
            duplicates.append(i)
        seen.add(card_tuple)
    
    if not duplicates:
        print("✅ All cards are unique!")
    else:
        print(f"❌ Found {len(duplicates)} duplicates")
        return
    
    # Save cards
    data_dir = 'data'
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    
    output_file = os.path.join(data_dir, 'bingo_cards.json')
    with open(output_file, 'w') as f:
        json.dump(cards, f, indent=2)
    
    print(f"\n💾 Saved {len(cards)} cards to {output_file}")
    
    # Show samples
    print("\n📋 Sample Card #1:")
    print(format_card_display(cards[0]))
    
    print("\n📋 Sample Card #200:")
    print(format_card_display(cards[199]))
    
    # Quick check of column distributions
    print("\n🔢 Quick distribution check:")
    sample = cards[0]
    for col_name, (indices, (low, high)) in [
        ("B", ([0, 5, 10, 15, 20], (1, 15))),
        ("I", ([1, 6, 11, 16, 21], (16, 30))),
        ("N", ([2, 7, 12, 17, 22], (31, 45))),
        ("G", ([3, 8, 13, 18, 23], (46, 60))),
        ("O", ([4, 9, 14, 19, 24], (61, 75)))
    ]:
        values = [sample[i] for i in indices if i != 12]
        print(f"{col_name}: {values} ✓")
    
    print("\n" + "=" * 50)
    print("🎉 Card generation completed!")
    print("=" * 50)

if __name__ == "__main__":
    main()