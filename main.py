"""
main.py - Full end-to-end pipeline orchestrator.

Supports THREE data sources, on purpose (not by accident):
  --data synthetic (default) : fully fake data with KNOWN, planted faults.
                                Fast, no internet needed. Proves detection
                                works, because we know the right answer.
  --data real                 : real historical weather from Open-Meteo,
                                 no faults injected. Proves the pipeline
                                 doesn't crash/misbehave on real-world
                                 data. Recall can't be measured here (no
                                 known ground truth) - the pipeline says
                                 so honestly instead of faking a number.
  --data hybrid                : REAL weather as the baseline + our SAME
                                  known faults injected on top. Strongest
                                  test: realistic patterns AND a known
                                  ground truth to measure accuracy against.

Run:
  python main.py                   (synthetic, default)
  python main.py --data real       (run real_data_fetcher.py first)
  python main.py --data hybrid     (run real_data_fetcher.py first)
"""

import argparse
import os
import pandas as pd

import data_simulation
import hybrid_data
from detection import rules, physics, neighbor, ml_model
import fusion
import health_score
import notifications
from utils.buffering import buffer_reading_locally, sync_buffered_readings

KNOWN_INJECTED_ANOMALY_STATIONS = {"ST01", "ST02", "ST03", "ST04", "ST05", "ST06", "ST07", "ST08", "ST09", "ST10"}
REQUIRED_REAL_COLUMNS = [
    "station_id", "timestamp", "temperature", "pressure", "humidity"
]



def load_synthetic_data(scenario="default"):
    raw_df = data_simulation.build_dataset()
    raw_df = data_simulation.inject_anomalies(raw_df, scenario=scenario)
    raw_df.to_csv("aws_data.csv", index=False)
    return raw_df, True  # True = we know the ground truth for this data


def load_real_data():
    data_file = "real_aws_data.csv"
    if not os.path.exists(data_file):
        raise FileNotFoundError(
            f"{data_file} not found. Run 'python real_data_fetcher.py' first "
            "to download real weather data from Open-Meteo."
        )
    raw_df = pd.read_csv(data_file, parse_dates=["timestamp"])
    missing = [c for c in REQUIRED_REAL_COLUMNS if c not in raw_df.columns]
    if missing:
        raise ValueError(f"Missing required columns in {data_file}: {missing}")
    raw_df.to_csv("aws_data.csv", index=False)
    return raw_df, False  # False = no known ground truth, can't measure recall


def load_hybrid_data(scenario="default"):
    raw_df = hybrid_data.build_hybrid_dataset(scenario=scenario)  # raises FileNotFoundError itself if real_aws_data.csv is missing
    raw_df.to_csv("aws_data.csv", index=False)
    return raw_df, True  # True = we KNOW the ground truth (we injected the same known faults)


def main():
    parser = argparse.ArgumentParser(description="SIH26073 AWS Anomaly Detection Pipeline")
    parser.add_argument("--data", choices=["synthetic", "real", "hybrid"], default="synthetic",
                         help="Data source: 'synthetic' (default, fully fake + known faults), "
                              "'real' (Open-Meteo, no faults, tests stability), or "
                              "'hybrid' (real weather + our known faults injected on top)")
    parser.add_argument("--scenario", choices=["default", "gurugram"], default="default",
                         help="Which fault pattern to inject (synthetic/hybrid modes only). "
                              "'gurugram' replicates the real 2018 incident: an extended silent "
                              "period during which a major rain event goes unrecorded.")
    args = parser.parse_args()

    print("=" * 70)
    print(f"SIH26073 - AWS Anomaly Detection - Full Pipeline "
          f"[{args.data.upper()} DATA, {args.scenario.upper()} SCENARIO]")
    print("=" * 70)

    # ---- Step 1: Data ----
    print(f"\n[1/7] Loading {args.data} data...")
    if args.data == "synthetic":
        raw_df, has_ground_truth = load_synthetic_data(scenario=args.scenario)
    elif args.data == "hybrid":
        raw_df, has_ground_truth = load_hybrid_data(scenario=args.scenario)
    else:
        raw_df, has_ground_truth = load_real_data()
    print(f"  -> {len(raw_df):,} readings across {raw_df['station_id'].nunique()} stations")
    print(f"  -> {raw_df['timestamp'].min()} to {raw_df['timestamp'].max()}")

    # ---- Step 2: Detection layers (rules, physics, neighbor, ML) ----
    print("\n[2/7] Running rule-based checks (Layer 1)...")
    rule_df = rules.run(raw_df)
    print(f"  -> {len(rule_df)} flags")

    print("\n[3/7] Running physics-based checks (validated dew-point formula)...")
    physics_df = physics.run(raw_df)
    print(f"  -> {len(physics_df)} flags")

    print("\n[4/7] Running neighbor comparison (Layer 2, tampering detection)...")
    neighbor_df = neighbor.run(raw_df)
    print(f"  -> {len(neighbor_df)} flags")

    print("\n[5/7] Running ML model (Layer 3, Isolation Forest)...")
    ml_df = ml_model.run(raw_df)
    drift_overdue, drift_msg = ml_model.check_retrain_needed()
    print(f"  -> {len(ml_df)} flags | Model status: {drift_msg}")

    # ---- Step 3: Fusion (classification + confidence + trust state) ----
    print("\n[6/7] Fusing all layers into final verdicts...")
    final_df = fusion.combine(rule_df, physics_df, neighbor_df, ml_df)
    final_df.to_csv("final_report.csv", index=False)
    print(f"  -> {len(final_df)} unique anomaly events")
    if not final_df.empty:
        print("\n  Attribution breakdown:")
        print("  " + final_df["attribution"].value_counts().to_string().replace("\n", "\n  "))
        print("\n  Trust state breakdown:")
        print("  " + final_df["trust_state"].value_counts().to_string().replace("\n", "\n  "))

    if has_ground_truth:
        recall_metrics = fusion.compute_recall(final_df, KNOWN_INJECTED_ANOMALY_STATIONS)
        print(f"\n  Honest accuracy check (synthetic test set): "
              f"{recall_metrics['recall_on_synthetic_test_%']}% recall")
    else:
        print("\n  Ground truth: real historical data, no planted faults - "
              "recall/precision cannot be honestly computed without real IMD "
              "fault records. This run only proves the pipeline runs cleanly "
              "on real-world data.")

    # ---- Step 4: Health scores ----
    print("\n[7/7] Computing station health scores...")
    health_df = health_score.compute_health_scores(raw_df, final_df)
    health_df = health_score.save_to_history(health_df)
    health_df = health_score.add_life_predictions(health_df)
    health_df.to_csv("health_scores.csv", index=False)
    print(health_df.to_string(index=False))

    # ---- Step 5: Alerts (priority-based, role-routed) ----
    print("\nRouting alerts by role (Admin / Regional Operator / Field Technician / Forecaster)...")
    notifications.route_and_send(final_df, health_df)

    # ---- Step 6: Offline buffering demo ----
    buffer_reading_locally({"station_id": "ST01", "note": "demo reading while offline"})
    synced = sync_buffered_readings(is_online=True)
    print(f"\nOffline buffering demo: synced {synced} queued reading(s) on reconnect.")

    print("\n" + "=" * 70)
    print("Pipeline complete. Outputs: aws_data.csv, final_report.csv, health_scores.csv")
    print("=" * 70)


if __name__ == "__main__":
    main()
