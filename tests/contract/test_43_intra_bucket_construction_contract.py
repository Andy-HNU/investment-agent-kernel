from __future__ import annotations

from product_mapping import BucketCardinalityPreference, resolve_bucket_count


def test_bucket_count_resolution_prefers_explicit_user_request() -> None:
    resolution = resolve_bucket_count(
        bucket="satellite",
        bucket_weight=0.20,
        horizon_months=36,
        risk_preference="moderate",
        max_drawdown_tolerance=0.20,
        current_market_pressure_score=30.0,
        explicit_request=BucketCardinalityPreference(
            bucket="satellite",
            mode="target_count",
            target_count=5,
            min_count=None,
            max_count=None,
            source="user_requested",
        ),
        persisted_preference=BucketCardinalityPreference(
            bucket="satellite",
            mode="target_count",
            target_count=2,
            min_count=None,
            max_count=None,
            source="persisted_user",
        ),
    )

    assert resolution.requested_count == 5
    assert resolution.resolved_count == 5
    assert resolution.source == "explicit_user"
