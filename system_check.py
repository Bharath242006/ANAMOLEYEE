"""
system_check.py - Pre-flight self-test.

Run this BEFORE a live demo to catch problems early (missing packages,
broken imports, bad config) instead of finding out mid-demo. Checks
every module can be imported, config values are sane, and a tiny
end-to-end dry run completes without errors.

Run: python system_check.py
Exit code 0 = all checks passed, safe to demo.
Exit code 1 = something needs fixing first.
"""

import sys

CHECKS_PASSED = 0
CHECKS_FAILED = 0


def check(description, fn):
    global CHECKS_PASSED, CHECKS_FAILED
    try:
        fn()
        print(f"  [PASS] {description}")
        CHECKS_PASSED += 1
    except Exception as e:
        print(f"  [FAIL] {description}: {e}")
        CHECKS_FAILED += 1


def check_imports():
    import pandas  # noqa
    import numpy  # noqa
    import sklearn  # noqa


def check_sendgrid_available():
    import sendgrid  # noqa


def check_project_modules():
    import config  # noqa
    import data_simulation  # noqa
    import hybrid_data  # noqa
    import fusion  # noqa
    import health_score  # noqa
    import alerts  # noqa
    import notifications  # noqa
    from detection import rules, physics, neighbor, ml_model  # noqa
    from utils import buffering  # noqa


def check_config_sanity():
    import config
    assert config.TEMP_MIN < config.TEMP_MAX, "TEMP_MIN must be less than TEMP_MAX"
    assert config.HUMIDITY_MIN < config.HUMIDITY_MAX, "HUMIDITY_MIN must be less than HUMIDITY_MAX"
    assert config.WIND_MIN < config.WIND_MAX, "WIND_MIN must be less than WIND_MAX"
    assert config.PRESSURE_MIN < config.PRESSURE_MAX, "PRESSURE_MIN must be less than PRESSURE_MAX"
    assert 0 < config.ML_CONTAMINATION < 1, "ML_CONTAMINATION must be between 0 and 1"
    assert config.TRUST_CAUTION_CONFIDENCE < config.TRUST_QUARANTINE_CONFIDENCE, \
        "CAUTION threshold must be lower than QUARANTINE threshold"


def check_mini_pipeline_run():
    """Generates a tiny synthetic dataset using ONLY core 3 parameters and runs it
    through every detection layer + fusion, to catch integration bugs before demo."""
    import data_simulation
    from detection import rules, physics, neighbor, ml_model
    import fusion

    raw_df = data_simulation.build_dataset(include_optional=False)
    raw_df = data_simulation.inject_anomalies(raw_df)

    rule_df = rules.run(raw_df)
    physics_df = physics.run(raw_df)
    neighbor_df = neighbor.run(raw_df)
    ml_df = ml_model.run(raw_df)

    final_df = fusion.combine(rule_df, physics_df, neighbor_df, ml_df)
    assert len(final_df) > 0, "Expected at least some anomalies to be detected in the mini test run"



if __name__ == "__main__":
    print("=" * 60)
    print("SIH26073 - System Self-Test (pre-flight check)")
    print("=" * 60)

    print("\n1. Checking required packages...")
    check("pandas, numpy, scikit-learn importable", check_imports)
    check("sendgrid importable", check_sendgrid_available)

    print("\n2. Checking project modules...")
    check("all project modules import cleanly", check_project_modules)

    print("\n3. Checking configuration...")
    check("config.py thresholds are logically consistent", check_config_sanity)

    print("\n4. Running a mini end-to-end pipeline...")
    check("full detection pipeline runs without errors", check_mini_pipeline_run)

    print("\n" + "=" * 60)
    print(f"RESULT: {CHECKS_PASSED} passed, {CHECKS_FAILED} failed")
    print("=" * 60)

    if CHECKS_FAILED > 0:
        print("\nFix the failed checks above before your demo.")
        sys.exit(1)
    else:
        print("\nAll checks passed. System is ready to demo.")
        sys.exit(0)
