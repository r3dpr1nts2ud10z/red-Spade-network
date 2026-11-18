from flask import Flask, jsonify, request
import os

app = Flask(__name__)

@app.route('/status', methods=['GET'])
def status():
    return jsonify({"status": "online"})

@app.route('/command', methods=['POST'])
def command():
    data = request.json
    print("Received command:", data)
    return jsonify({"status": "success", "job_id": "job_12345"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
