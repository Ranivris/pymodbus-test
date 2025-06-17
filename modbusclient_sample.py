# final_client.py

from flask import Flask, jsonify, render_template_string, request
from pymodbus.client import ModbusTcpClient

# --- Modbus 클라이언트 함수 ---
def read_registers(client, unit_id, fc, address, count):
    """Modbus 읽기 요청을 처리하는 범용 함수"""
    read_map = {
        2: client.read_discrete_inputs,
        3: client.read_holding_registers,
    }
    func = read_map.get(fc)
    if not func:
        return None, f"지원하지 않는 Function Code: {fc}"

    response = func(address, count=count, slave=unit_id)
    if response.isError():
        return None, f"읽기 오류: {response}"

    return response.registers if fc == 3 else response.bits[:count], None

def write_coil_register(client, unit_id, address, value):
    """코일 쓰기 요청을 처리하는 함수"""
    response = client.write_coil(address, value, slave=unit_id)
    if response.isError():
        return False, f"쓰기 오류: {response}"
    return True, None

# --- Flask 라우트 ---
app = Flask(__name__)

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/api/data', methods=['GET'])
def get_data():
    client = ModbusTcpClient("127.0.0.1", port=5020, timeout=2)
    if not client.connect():
        return jsonify({"error": "서버 연결 실패"}), 500

    try:
        hr1, err1 = read_registers(client, 1, 3, 0, 5)
        di1, err2 = read_registers(client, 1, 2, 0, 5)
        hr2, err3 = read_registers(client, 2, 3, 0, 5)
        di2, err4 = read_registers(client, 2, 2, 0, 5)

        if any([err1, err2, err3, err4]):
            return jsonify({"error": f"{err1 or err2 or err3 or err4}"}), 500

        return jsonify({
            "registers_1": hr1, "inputs_1": di1,
            "registers_2": hr2, "inputs_2": di2,
        })
    finally:
        client.close()

@app.route('/api/write_coil', methods=['POST'])
def set_coil():
    try:
        unit_id = int(request.args.get('unitId'))
        address = int(request.args.get('address'))
        value = bool(int(request.args.get('value')))
    except (TypeError, ValueError):
        return jsonify({"error": "잘못된 파라미터"}), 400

    client = ModbusTcpClient("127.0.0.1", port=5020, timeout=2)
    if not client.connect():
        return jsonify({"error": "서버 연결 실패"}), 500

    try:
        success, error = write_coil_register(client, unit_id, address, value)
        if not success:
            return jsonify({"error": error}), 500
        return jsonify({"success": True}), 200
    finally:
        client.close()

# --- 웹페이지 HTML & JavaScript ---
HTML_PAGE = """
<!doctype html>
<html lang="ko">
<head>
    <meta charset="utf-8">
    <title>HVAC 제어 시스템</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; display: flex; flex-direction: column; align-items: center; background-color: #f0f2f5; margin: 0; }
        h3 { margin: 20px 0; color: #1f2937; }
        table { width: 95%; max-width: 1000px; border-collapse: collapse; text-align: center; background-color: white; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); border-radius: 8px; overflow: hidden; }
        th, td { padding: 12px 15px; }
        thead { background-color: #4f46e5; color: white; }
        tbody tr:nth-child(even) { background-color: #f8f9fa; }
        tbody tr:hover { background-color: #e9ecef; }
        button { padding: 6px 12px; margin: 0 4px; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; transition: all 0.2s ease-in-out; }
        .on-button { background-color: #22c55e; color: white; } .on-button:hover { background-color: #16a34a; }
        .off-button { background-color: #ef4444; color: white; } .off-button:hover { background-color: #dc2626; }
    </style>
<script>
    async function fetchData() {
        try {
            const response = await fetch('/api/data');
            const data = await response.json();
            if (data.error) {
                console.error("API Error:", data.error);
                return;
            }
            updateTable(data);
        } catch (error) {
            console.error('Fetch Error:', error);
        }
    }

    function updateTable(data) {
        const tableBody = document.getElementById('modbus-table-body');
        const allRegisters = (data.registers_1 || []).concat(data.registers_2 || []);
        const allInputs = (data.inputs_1 || []).concat(data.inputs_2 || []);
        let tableHTML = '';

        for (let i = 0; i < 10; i++) {
            const unitId = i < 5 ? 1 : 2;
            const address = i % 5;
            const temp = allRegisters[i] ?? 'N/A';
            const status = typeof allInputs[i] === 'boolean' ? (allInputs[i] ? '🟢 ON' : '🔴 OFF') : 'N/A';
            const alertIcon = temp >= 28 ? '🚨' : '';

            tableHTML += `
                <tr>
                    <td>에어컨 ${i + 1}</td>
                    <td>${temp} ${alertIcon}</td>
                    <td>${status}</td>
                    <td>
                        <button class="on-button" onclick="writeCoil(${unitId}, ${address}, 1)">ON</button>
                        <button class="off-button" onclick="writeCoil(${unitId}, ${address}, 0)">OFF</button>
                    </td>
                </tr>`;
        }
        tableBody.innerHTML = tableHTML;
    }

    async function writeCoil(unitId, address, value) {
        await fetch(`/api/write_coil?unitId=${unitId}&address=${address}&value=${value}`, { method: 'POST' });
        setTimeout(fetchData, 200); // 쓰기 후 0.2초 뒤에 데이터 즉시 갱신
    }

    setInterval(fetchData, 2500); // 2.5초마다 데이터 자동 갱신
    window.onload = fetchData;
</script>
</head>
<body>
    <h3>HVAC 제어 시스템</h3>
    <table>
        <thead><tr><th>장치</th><th>온도 (°C)</th><th>상태</th><th>명령</th></tr></thead>
        <tbody id="modbus-table-body"></tbody>
    </table>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
