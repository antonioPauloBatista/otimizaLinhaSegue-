import requests
import base64
import datetime
import json

GRAFANA_URL = "http://10.91.7.221:3000"
GRAFANA_USER = "admin"
GRAFANA_PASSWORD = "!ambev2021"
DATASOURCE_SELECTOR = "17"
BUCKET = "Segue"
MEASUREMENT = "502"

session = requests.Session()
usr_pass = f"{GRAFANA_USER}:{GRAFANA_PASSWORD}".encode("utf-8")
b64_val = base64.b64encode(usr_pass).decode("utf-8")
headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": f"Basic {b64_val}"
}

ds_url = f"{GRAFANA_URL.rstrip('/')}/api/datasources"
ds_response = session.get(ds_url, headers=headers, timeout=10)
if ds_response.status_code == 200:
    ds_list = ds_response.json()
    uid = None
    for ds in ds_list:
        if ds.get("type") == "influxdb":
            if str(ds.get("id")) == DATASOURCE_SELECTOR or ds.get("name").lower() == DATASOURCE_SELECTOR.lower():
                uid = ds.get("uid")
                break
    if not uid:
        print("Datasource not found.")
        exit(1)
    
    # Query last 2 minutes
    agora = datetime.datetime.now(datetime.timezone.utc)
    t_start = agora - datetime.timedelta(minutes=30)
    t_stop = agora
    
    t_start_str = t_start.strftime('%Y-%m-%dT%H:%M:%SZ')
    t_stop_str = t_stop.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    flux_query = f'''from(bucket: "{BUCKET}")
  |> range(start: {t_start_str}, stop: {t_stop_str})
  |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
  |> filter(fn: (r) => r["_field"] == "accumulation_percentage")
  |> last()
  |> pivot(rowKey:["_measurement"], columnKey: ["_field", "buffer_name_local", "machine_name_generic"], valueColumn: "_value")'''

    ds_query_url = f"{GRAFANA_URL.rstrip('/')}/api/ds/query"
    ds_payload = {
        "queries": [
            {
                "datasource": {"uid": uid, "type": "influxdb"},
                "query": flux_query,
                "queryType": "flux",
                "refId": "A",
                "maxDataPoints": 100,
                "intervalMs": 30000
            }
        ]
    }
    
    resp = session.post(ds_query_url, headers=headers, json=ds_payload)
    print("STATUS:", resp.status_code)
    print("JSON:", json.dumps(resp.json(), indent=2))
else:
    print("Failed to get datasources:", ds_response.status_code)
