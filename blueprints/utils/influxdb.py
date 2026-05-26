from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from flask import current_app
from datetime import datetime, timezone


def _client():
    return InfluxDBClient(
        url=current_app.config['INFLUXDB_URL'],
        token=current_app.config['INFLUXDB_TOKEN'],
        org=current_app.config['INFLUXDB_ORG'],
    )


def write_push_data(beehive_id, data_points):
    """Write a list of {timestamp, temperature?, humidity?} dicts from a push."""
    points = []
    for row in data_points:
        try:
            ts = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
        except (KeyError, ValueError):
            ts = datetime.now(timezone.utc)

        if row.get('temperature') is not None:
            points.append(
                Point("temperature")
                .tag("beehive_id", str(beehive_id))
                .field("value", float(row['temperature']))
                .time(ts, WritePrecision.S)
            )
        if row.get('humidity') is not None:
            points.append(
                Point("humidity")
                .tag("beehive_id", str(beehive_id))
                .field("value", float(row['humidity']))
                .time(ts, WritePrecision.S)
            )

    if not points:
        return
    with _client() as c:
        c.write_api(write_options=SYNCHRONOUS).write(
            bucket=current_app.config['INFLUXDB_BUCKET'],
            org=current_app.config['INFLUXDB_ORG'],
            record=points,
        )


_RANGE = {'1h', '6h', '24h', '7d', '30d'}
_WINDOW = {'1h': '1m', '6h': '5m', '24h': '15m', '7d': '1h', '30d': '6h'}


def query_chart_data(beehive_id, range_str='24h'):
    if range_str not in _RANGE:
        range_str = '24h'
    bucket = current_app.config['INFLUXDB_BUCKET']
    org = current_app.config['INFLUXDB_ORG']
    window = _WINDOW[range_str]
    query = f'''
from(bucket: "{bucket}")
  |> range(start: -{range_str})
  |> filter(fn: (r) => r["beehive_id"] == "{beehive_id}")
  |> filter(fn: (r) => r._measurement == "temperature" or r._measurement == "humidity")
  |> aggregateWindow(every: {window}, fn: mean, createEmpty: false)
  |> yield(name: "mean")
'''
    result = {
        'temperature': {'labels': [], 'data': []},
        'humidity': {'labels': [], 'data': []},
    }
    with _client() as c:
        for table in c.query_api().query(query, org=org):
            if not table.records:
                continue
            measurement = table.records[0].get_measurement()
            if measurement not in result:
                continue
            for r in table.records:
                result[measurement]['labels'].append(r.get_time().strftime('%Y-%m-%dT%H:%M:%SZ'))
                val = r.get_value()
                result[measurement]['data'].append(round(val, 2) if val is not None else None)
    return result


def list_beehives():
    """Return distinct beehive IDs and their last known values."""
    bucket = current_app.config['INFLUXDB_BUCKET']
    org = current_app.config['INFLUXDB_ORG']
    query = f'''
from(bucket: "{bucket}")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "temperature" or r._measurement == "humidity")
  |> last()
  |> keep(columns: ["beehive_id", "_measurement", "_value", "_time"])
'''
    beehives = {}
    with _client() as c:
        for table in c.query_api().query(query, org=org):
            for r in table.records:
                bid = r.values.get('beehive_id', 'unknown')
                if bid not in beehives:
                    beehives[bid] = {}
                val = r.get_value()
                beehives[bid][r.get_measurement()] = {
                    'value': round(val, 2) if val is not None else None,
                    'time': r.get_time().strftime('%Y-%m-%dT%H:%M:%SZ'),
                }
    return beehives
