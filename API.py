from flask import Flask, jsonify
from influxdb_client import InfluxDBClient

# 1. On initialise l'API (le serveur de restaurant)
app = Flask(__name__)

# 2. Vos identifiants InfluxDB (La clé de la cuisine)
INFLUX_URL = "http://192.168.1.149:8086/" # Mettez l'IP du Raspberry si vous codez sur votre PC
INFLUX_TOKEN = "3D2K4cFn-oVjJVg9U7ENqTKF9QyM0LDDYuQs7Ch64VRaYn9hnym_XPXuZZjsx0NRkHX5X6Dy_99YTU_sZtRx_A=="
INFLUX_ORG = "beetter"
INFLUX_BUCKET = "sensors"
from flask import Flask, jsonify
from influxdb_client import InfluxDBClient

app = Flask(__name__)

# Identifiants InfluxDB
INFLUX_URL = "http://192.168.1.149:8086/" 
INFLUX_TOKEN = "3D2K4cFn-oVjJVg9U7ENqTKF9QyM0LDDYuQs7Ch64VRaYn9hnym_XPXuZZjsx0NRkHX5X6Dy_99YTU_sZtRx_A=="
INFLUX_ORG = "beetter"
INFLUX_BUCKET = "sensors"

# ==========================================
# LA FONCTION À TOUT FAIRE (Le Cuisinier)
# ==========================================
def interroger_influxdb(id_ruche, measurement, field, nom_valeur):
    """Ouvre InfluxDB, cherche la donnée demandée, et renvoie une liste propre."""
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    query_api = client.query_api()

    requete = f"""
        from(bucket: "{INFLUX_BUCKET}")
        |> range(start: -2h)
        |> filter(fn: (r) => r["_measurement"] == "{measurement}")
        |> filter(fn: (r) => r["id_ruche"] == "{id_ruche}")
        |> filter(fn: (r) => r["_field"] == "{field}")
    """
    
    resultats_bruts = query_api.query(requete)
    donnees_propres = []
    
    for table in resultats_bruts:
        for ligne in table.records:
            donnees_propres.append({
                "heure": ligne.get_time().strftime("%H:%M:%S"),
                nom_valeur: ligne.get_value() # Le nom s'adapte au capteur !
            })

    client.close()
    return donnees_propres

# ==========================================
# LES ROUTES DE L'API (Le Menu)
# ==========================================

@app.route('/api/ruche/<id_ruche>/temperature/int', methods=['GET'])
def obtenir_temp_int(id_ruche):
    donnees = interroger_influxdb(id_ruche, "ruche_meteo", "temperature_int", "temperature_int")
    return jsonify(donnees)

@app.route('/api/ruche/<id_ruche>/temperature/ext', methods=['GET'])
def obtenir_temp_ext(id_ruche):
    donnees = interroger_influxdb(id_ruche, "ruche_meteo", "temperature_ext", "temperature_ext")
    return jsonify(donnees)

@app.route('/api/ruche/<id_ruche>/hygrometrie/int', methods=['GET'])
def obtenir_hygro_int(id_ruche):
    donnees = interroger_influxdb(id_ruche, "ruche_meteo", "hygrométrie", "humidite")
    return jsonify(donnees)

@app.route('/api/ruche/<id_ruche>/micro/int', methods=['GET'])
def obtenir_micro_int(id_ruche):
    donnees = interroger_influxdb(id_ruche, "ruche_son", "microphone_int", "decibels_int")
    return jsonify(donnees)

@app.route('/api/ruche/<id_ruche>/micro/ext', methods=['GET'])
def obtenir_micro_ext(id_ruche):
    donnees = interroger_influxdb(id_ruche, "ruche_son", "microphone_ext", "decibels_ext")
    return jsonify(donnees)

if __name__ == '__main__':
    # host='0.0.0.0' permet d'accepter les requêtes de n'importe quel téléphone sur le réseau
    app.run(host='0.0.0.0', port=5000, debug=True)