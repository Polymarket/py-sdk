"""Inspect directional IDs offline: uv run python -m examples.directional_positions."""

from polymarket import (
    decode_position_id,
    derive_directional_bucket_positions,
    derive_directional_threshold_positions,
)


def main() -> None:
    event_id = "0x0400112233445566778899aabbccddeeff000400000000000000000102"
    low = derive_directional_threshold_positions(event_id=event_id, line=1)
    high = derive_directional_threshold_positions(event_id=event_id, line=3)
    bucket = derive_directional_bucket_positions(event_id=event_id, bucket_index=2)
    print("Lower ABOVE:", decode_position_id(low.above_position_id))
    print("Higher BELOW:", decode_position_id(high.below_position_id))
    print("Residual bucket:", bucket)
    # With a configured client and settled wings:
    # transaction = client.merge_directional(low.above_position_id, high.below_position_id)
    # transaction.wait()
    # Reverse one pair using the same IDs, in either order:
    # client.split_directional(high.below_position_id, low.above_position_id,
    #                          amount=1_000_000).wait()


if __name__ == "__main__":
    main()
