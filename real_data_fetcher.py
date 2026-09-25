"""Fetch 365 days of hourly Open-Meteo data for 50 representative Indian locations.
These are representative coordinates, not claims of official AWS stations.
Dew point is NOT fetched; it is calculated locally from temperature + RH.
"""
import time
import requests
import pandas as pd
import numpy as np

STATIONS = {
    'ST01': (28.61,77.20),'ST02': (19.07,72.87),'ST03': (13.08,80.27),'ST04': (12.97,77.59),'ST05': (22.57,88.36),
    'ST06': (23.03,72.58),'ST07': (26.85,80.95),'ST08': (17.38,78.49),'ST09': (15.30,74.12),'ST10': (30.74,76.78),
    'ST11': (23.26,77.41),'ST12': (21.15,79.09),'ST13': (18.52,73.86),'ST14': (17.69,83.22),'ST15': (11.02,76.96),
    'ST16': (9.93,76.27),'ST17': (10.79,78.70),'ST18': (8.52,76.94),'ST19': (11.25,75.78),'ST20': (12.30,76.65),
    'ST21': (15.49,73.83),'ST22': (21.17,72.83),'ST23': (22.30,73.20),'ST24': (24.59,73.71),'ST25': (26.91,75.79),
    'ST26': (26.24,73.02),'ST27': (27.18,78.01),'ST28': (25.32,82.97),'ST29': (25.59,85.14),'ST30': (23.34,85.31),
    'ST31': (22.72,75.86),'ST32': (21.25,81.63),'ST33': (19.07,82.02),'ST34': (20.30,85.82),'ST35': (19.88,75.34),
    'ST36': (17.98,79.60),'ST37': (16.51,80.63),'ST38': (16.30,80.44),'ST39': (14.68,77.60),'ST40': (14.47,78.82),
    'ST41': (11.67,92.74),'ST42': (24.81,93.94),'ST43': (26.14,91.74),'ST44': (25.57,91.88),'ST45': (27.33,88.61),
    'ST46': (23.83,91.28),'ST47': (26.14,85.38),'ST48': (30.32,78.03),'ST49': (31.10,77.17),'ST50': (32.22,76.32),
}
DAYS_OF_HISTORY = 365
BASE_URL = 'https://archive-api.open-meteo.com/v1/archive'

def calculate_dew_point(temp_c, humidity_pct):
    t = pd.Series(temp_c, dtype='float64')
    rh = pd.Series(humidity_pct, dtype='float64').clip(lower=1, upper=100)
    gamma = np.log(rh/100.0) + (17.62*t)/(243.12+t)
    return (243.12*gamma)/(17.62-gamma)

def fetch_station_history(station_id, lat, lon, days=DAYS_OF_HISTORY):
    end_date = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    start_date = end_date - pd.Timedelta(days=days-1)
    params = {
        'latitude':lat,'longitude':lon,'start_date':start_date.strftime('%Y-%m-%d'),'end_date':end_date.strftime('%Y-%m-%d'),
        'hourly':'temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m,surface_pressure,shortwave_radiation,cloud_cover',
        'timezone':'UTC'
    }
    r = requests.get(BASE_URL, params=params, timeout=60)
    r.raise_for_status()
    h = r.json()['hourly']
    df = pd.DataFrame({'station_id':station_id,'lat':lat,'lon':lon,'timestamp':pd.to_datetime(h['time']),
        'temperature':h['temperature_2m'],'rainfall':h['precipitation'],'humidity':h['relative_humidity_2m'],
        'wind_speed':h['wind_speed_10m'],'wind_direction':h['wind_direction_10m'],'pressure':h['surface_pressure'],
        'solar_radiation':h['shortwave_radiation'],'cloud_cover':h['cloud_cover']})
    df['dew_point'] = calculate_dew_point(df['temperature'], df['humidity']).round(2)
    return df

def fetch_all_stations():
    frames=[]
    for sid,(lat,lon) in STATIONS.items():
        print(f'Fetching {DAYS_OF_HISTORY} days for {sid} ({lat}, {lon})...')
        try:
            df=fetch_station_history(sid,lat,lon); frames.append(df); print(f'  -> {len(df)} hourly readings')
        except Exception as e: print(f'  -> FAILED: {e}')
        time.sleep(1)
    if not frames: raise RuntimeError('No station data was fetched.')
    return pd.concat(frames,ignore_index=True).dropna(subset=['temperature','humidity','pressure']).sort_values(['station_id','timestamp']).reset_index(drop=True)

if __name__=='__main__':
    df=fetch_all_stations(); df.to_csv('real_aws_data.csv',index=False)
    print(f'\nDone. Total readings: {len(df):,} across {df.station_id.nunique()} representative locations')
    print(f'Date range: {df.timestamp.min()} to {df.timestamp.max()}')
    print('Saved to real_aws_data.csv')
