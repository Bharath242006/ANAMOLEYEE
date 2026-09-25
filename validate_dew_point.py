"""One-time validation of our dew point calculation against Open-Meteo dew_point_2m."""
import time, requests, pandas as pd
from real_data_fetcher import STATIONS, DAYS_OF_HISTORY, BASE_URL, calculate_dew_point

def validate_station(sid,lat,lon,days=DAYS_OF_HISTORY):
    end=pd.Timestamp.today().normalize()-pd.Timedelta(days=1); start=end-pd.Timedelta(days=days-1)
    params={'latitude':lat,'longitude':lon,'start_date':start.strftime('%Y-%m-%d'),'end_date':end.strftime('%Y-%m-%d'),
            'hourly':'temperature_2m,relative_humidity_2m,dew_point_2m','timezone':'UTC'}
    r=requests.get(BASE_URL,params=params,timeout=60); r.raise_for_status(); h=r.json()['hourly']
    d=pd.DataFrame({'station_id':sid,'timestamp':pd.to_datetime(h['time']),'temperature':h['temperature_2m'],'humidity':h['relative_humidity_2m'],'open_meteo_dew_point':h['dew_point_2m']})
    d['our_dew_point']=calculate_dew_point(d.temperature,d.humidity); d['absolute_difference_c']=(d.open_meteo_dew_point-d.our_dew_point).abs(); return d
if __name__=='__main__':
    frames=[]
    for sid,(lat,lon) in STATIONS.items():
        print(f'Validating {sid}...')
        try: frames.append(validate_station(sid,lat,lon))
        except Exception as e: print(f'  -> FAILED: {e}')
        time.sleep(1)
    if not frames: raise RuntimeError('No validation data fetched.')
    d=pd.concat(frames,ignore_index=True); d.to_csv('dew_point_validation.csv',index=False)
    print('\n=== Dew Point Validation ===')
    print(f'Samples: {len(d):,}'); print(f"Mean absolute difference: {d.absolute_difference_c.mean():.3f} °C")
    print(f"Median absolute difference: {d.absolute_difference_c.median():.3f} °C")
    print(f"Max absolute difference: {d.absolute_difference_c.max():.3f} °C")
    print(f"Within 0.5°C: {(d.absolute_difference_c<=0.5).mean()*100:.2f}%")
    print('Saved to dew_point_validation.csv')
