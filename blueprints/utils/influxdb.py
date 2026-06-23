from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from flask import current_app
from datetime import datetime, timezone

# Must stay in sync with the Raspberry Pi app's measurement set
# (app/blueprints/utils/influxdb.py : MEASUREMENTS).
MEASUREMENTS = (
    'temperature_int', 'humidity_int',
    'temperature_ext', 'humidity_ext',
    'sound_freq_int', 'sound_amp_int',
    'sound_freq_ext', 'sound_amp_ext',
    'light_ext',
)


def _measurement_filter():
    return ' or '.join(f'r._measurement == "{m}"' for m in MEASUREMENTS)


def _client():
    return InfluxDBClient(
        url=current_app.config['INFLUXDB_URL'],
        token=current_app.config['INFLUXDB_TOKEN'],
        org=current_app.config['INFLUXDB_ORG'],
        timeout=10_000,  # 10 secondes max
    )


def write_push_data(beehive_id, data_points):
    """Write a list of pushed rows.

    Each row is {timestamp, <measurement>: value, ...} where <measurement>
    is any of MEASUREMENTS (temperature_int, humidity_int, ..., light_ext).
    """
    points = []
    for row in data_points:
        try:
            ts = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
        except (KeyError, ValueError):
            ts = datetime.now(timezone.utc)

        for measurement in MEASUREMENTS:
            value = row.get(measurement)
            if value is None:
                continue
            points.append(
                Point(measurement)
                .tag("beehive_id", str(beehive_id))
                .field("value", float(value))
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
  |> filter(fn: (r) => {_measurement_filter()})
  |> aggregateWindow(every: {window}, fn: mean, createEmpty: false)
  |> yield(name: "mean")
'''
    result = {m: {'labels': [], 'data': []} for m in MEASUREMENTS}
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
  |> filter(fn: (r) => {_measurement_filter()})
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
