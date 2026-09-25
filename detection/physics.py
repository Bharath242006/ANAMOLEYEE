import numpy as np
import pandas as pd

def estimate_dew_point(temp_c, humidity_pct):
    if pd.isna(temp_c) or pd.isna(humidity_pct):
        return np.nan
    rh = float(np.clip(humidity_pct, 1, 100))
    t = float(temp_c)
    gamma = np.log(rh / 100.0) + (17.62 * t) / (243.12 + t)
    return (243.12 * gamma) / (17.62 - gamma)

def add_derived_features(df):
    df = df.copy()
    if 'temperature' in df.columns and 'humidity' in df.columns:
        df['dew_point'] = [estimate_dew_point(t, h) for t, h in zip(df['temperature'], df['humidity'])]
    else:
        df['dew_point'] = np.nan

    df = df.sort_values(['station_id', 'timestamp']).copy()
    if 'timestamp' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    time_gaps = df.groupby('station_id')['timestamp'].diff().dt.total_seconds().fillna(0) / 3600

    gap_block = (time_gaps > 12).cumsum()

    for col in ['temperature', 'humidity', 'pressure']:
        if col in df.columns:
            rolling = df.groupby(['station_id', gap_block])[col].transform(lambda x: x.rolling(24, min_periods=1).mean())
            df[f'{col}_deviation'] = df[col] - rolling
            diff_ser = df.groupby(['station_id', gap_block])[col].transform(lambda x: x.diff().fillna(0))
            df[f'{col}_rate_of_change'] = diff_ser
            std = df.groupby(['station_id', gap_block])[col].transform(lambda x: x.std())
            mean = df.groupby(['station_id', gap_block])[col].transform(lambda x: x.mean())
            df[f'{col}_zscore'] = np.where((pd.notna(std) & (std > 0)), (df[col] - mean) / std, 0.0)

    if 'temperature' in df.columns and 'humidity' in df.columns:
        df['temp_humidity_ratio'] = df['temperature'] / np.maximum(df['humidity'], 1.0)

    # Optional features (only if present)
    if 'wind_speed' in df.columns:
        rolling = df.groupby('station_id')['wind_speed'].transform(lambda x: x.rolling(24, min_periods=1).mean())
        df['wind_speed_deviation'] = df['wind_speed'] - rolling
    if 'rainfall' in df.columns:
        df['rainfall_rolling_6h'] = df.groupby('station_id')['rainfall'].transform(lambda x: x.rolling(6, min_periods=1).mean())
    if 'wind_direction' in df.columns:
        df['wind_direction_change'] = df.groupby('station_id')['wind_direction'].transform(lambda x: x.diff().abs().fillna(0))
    return df

def run(df):
    flags = []
    work = add_derived_features(df)
    for _, row in work.iterrows():
        reasons = []

        # 1. Dew point physical consistency
        dp = row.get('dew_point')
        temp = row.get('temperature')
        hum = row.get('humidity')
        pres = row.get('pressure')

        if pd.notna(dp) and pd.notna(temp) and dp > temp + 0.5:
            diff_c = round(float(dp - temp), 2)
            flags.append({
                'station_id': row['station_id'],
                'timestamp': row['timestamp'],
                'flag_type': 'Physics violation',
                'reason': f'Calculated dew point ({dp:.1f}°C) exceeds air temperature ({temp}°C) - temp or humidity sensor is faulty',
                'dew_point_diff_c': diff_c
            })
            continue

        # 2. Abnormal T-RH combination (e.g. extremely high temp with extremely high humidity)
        if pd.notna(temp) and pd.notna(hum):
            if temp > 45.0 and hum > 85.0:
                reasons.append(f"Abnormal T-RH combination (Temp {temp}°C with RH {hum}% is physically implausible)")

        # 3. Pressure temporal rate of change consistency
        pres_roc = row.get('pressure_rate_of_change')
        if pd.notna(pres_roc) and abs(pres_roc) > 12.0:
            reasons.append(f"Abnormal pressure jump/drop ({pres_roc:.1f} hPa shift between consecutive readings)")

        # 4. Cross-parameter inconsistency (e.g. severe temperature deviation without moisture/pressure shift)
        temp_dev = row.get('temperature_deviation')
        hum_dev = row.get('humidity_deviation')
        if pd.notna(temp_dev) and pd.notna(hum_dev):
            if abs(temp_dev) > 15.0 and abs(hum_dev) < 2.0:
                reasons.append(f"Cross-parameter inconsistency (Temperature shifted by {temp_dev:.1f}°C while Humidity remained completely static)")

        if reasons:
            flags.append({
                'station_id': row['station_id'],
                'timestamp': row['timestamp'],
                'flag_type': 'Physics violation',
                'reason': '; '.join(reasons),
                'dew_point_diff_c': round(float(dp - temp), 2) if (pd.notna(dp) and pd.notna(temp)) else 0.0
            })
            
    return pd.DataFrame(flags)

