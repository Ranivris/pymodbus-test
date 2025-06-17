from flask import Flask, jsonify, render_template_string, request
from pymodbus.client import ModbusTcpClient

# --- Modbus 클라이언트 함수 ---
def read_registers(client, unit_id, fc, address, count):
    read_map = {
        2: client.read_discrete_inputs,
        3: client.read_holding_registers,
    }
    func = read_map.get(fc)
    if not func:
        return None, f"지원하지 않는 Function Code: {fc}"
    try:
        response = func(address, count=count, slave=unit_id)
        if response.isError():
            return None, f"읽기 오류: {response}"
        return response.registers if fc == 3 else response.bits[:count], None
    except Exception as e:
        return None, f"Modbus 통신 예외: {e}"

def write_coil_register(client, unit_id, address, value):
    try:
        response = client.write_coil(address, value, slave=unit_id)
        if response.isError():
            return False, f"쓰기 오류: {response}"
        return True, None
    except Exception as e:
        return False, f"Modbus 통신 예외: {e}"

def write_single_holding_register(client, unit_id, address, value):
    """Holding register 한 개 쓰기 요청을 처리하는 함수"""
    try:
        response = client.write_register(address, value, slave=unit_id)
        if response.isError():
            return False, f"쓰기 오류: {response}"
        return True, None
    except Exception as e:
        return False, f"Modbus 통신 예외: {e}"

# --- Flask 라우트 ---
app = Flask(__name__)

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/api/data', methods=['GET'])
def get_data():
    client = ModbusTcpClient("127.0.0.1", port=5020, timeout=2)
    if not client.connect():
        return jsonify({"error": "Modbus 서버 연결 실패"}), 500
    try:
        hr1_all, err1_hr = read_registers(client, 1, 3, 0, 18) # 6 temps + 6 high_T + 6 good_T
        di1_status, err1_di = read_registers(client, 1, 2, 0, 6) # 6 AC statuses
        hr2_all, err2_hr = read_registers(client, 2, 3, 0, 18)
        di2_status, err2_di = read_registers(client, 2, 2, 0, 6)

        errors = [e for e in [err1_hr, err1_di, err2_hr, err2_di] if e]
        if errors:
            return jsonify({"error": f"데이터 읽기 중 오류 발생: {'; '.join(errors)}"}), 500

        def process_hr_data(hr_data):
            if hr_data and len(hr_data) == 18:
                return hr_data[0:6], hr_data[6:12], hr_data[12:18]
            return [15]*6, [27]*6, [20]*6 # Defaults

        temps1, high_T1, good_T1 = process_hr_data(hr1_all)
        temps2, high_T2, good_T2 = process_hr_data(hr2_all)

        return jsonify({
            "temperatures_1": temps1,
            "high_thresholds_1": high_T1,
            "good_thresholds_1": good_T1,
            "inputs_1": di1_status if di1_status else [False]*6,
            "temperatures_2": temps2,
            "high_thresholds_2": high_T2,
            "good_thresholds_2": good_T2,
            "inputs_2": di2_status if di2_status else [False]*6,
        })
    finally:
        client.close()

@app.route('/api/write_coil', methods=['POST'])
def set_coil():
    try:
        unit_id = int(request.args.get('unitId'))
        address = int(request.args.get('address')) # This is acIndex (0-5)
        value = bool(int(request.args.get('value')))
    except: return jsonify({"error": "잘못된 파라미터 (코일)"}), 400

    client = ModbusTcpClient("127.0.0.1", port=5020, timeout=2)
    if not client.connect(): return jsonify({"error": "Modbus 서버 연결 실패"}), 500
    try:
        success, error = write_coil_register(client, unit_id, address, value)
        return jsonify({"success": True}) if success else jsonify({"error": error}), (200 if success else 500)
    finally: client.close()

@app.route('/api/write_temp_threshold', methods=['POST'])
def set_temp_threshold(): # Renamed from write_temp_thresholds
    try:
        unit_id = int(request.args.get('unitId'))
        ac_index = int(request.args.get('acIndex')) # 0-5
        high_temp = int(request.args.get('highTemp'))
        good_temp = int(request.args.get('goodTemp'))

        if not (0 <= ac_index <= 5):
            return jsonify({"error": "잘못된 AC 인덱스입니다."}), 400
        if not (0 <= high_temp <= 50 and 0 <= good_temp <= 50 and good_temp < high_temp):
            return jsonify({"error": "잘못된 온도 설정 값입니다."}), 400
    except: return jsonify({"error": "잘못된 파라미터 (온도 임계값)"}), 400

    client = ModbusTcpClient("127.0.0.1", port=5020, timeout=2)
    if not client.connect(): return jsonify({"error": "Modbus 서버 연결 실패"}), 500
    try:
        # High threshold address = 6 + ac_index
        # Good threshold address = 12 + ac_index
        addr_high_T = 6 + ac_index
        addr_good_T = 12 + ac_index

        success1, error1 = write_single_holding_register(client, unit_id, addr_high_T, high_temp)
        if not success1:
            return jsonify({"error": f"상한 온도 쓰기 실패: {error1}"}), 500

        success2, error2 = write_single_holding_register(client, unit_id, addr_good_T, good_temp)
        if not success2:
            # Potentially rollback or note partial success. For now, report second error.
            return jsonify({"error": f"하한 온도 쓰기 실패: {error2}"}), 500

        return jsonify({"success": True}), 200
    finally: client.close()

HTML_PAGE = """
<!doctype html>
<html lang="ko">
<head>
    <meta charset="utf-8">
    <title>HVAC 개별 제어 시스템</title>
    <style>
        body { font-family: sans-serif; display: flex; flex-direction: column; align-items: center; background-color: #f0f2f5; margin: 0; padding-bottom: 30px; }
        h3 { margin: 20px 0 10px 0; color: #1f2937; }
        table { width: 98%; max-width: 1200px; border-collapse: collapse; text-align: center; background-color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }
        th, td { padding: 10px 8px; border-bottom: 1px solid #e0e0e0; }
        thead { background-color: #4a5568; color: white; }
        tbody tr:nth-child(even) { background-color: #f7fafc; }
        tbody tr:hover { background-color: #edf2f7; }
        button { padding: 5px 10px; margin: 0 2px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; transition: background-color 0.2s; }
        .on-button { background-color: #48bb78; color: white; } .on-button:hover { background-color: #38a169; }
        .off-button { background-color: #f56565; color: white; } .off-button:hover { background-color: #e53e3e; }
        .save-button { background-color: #4299e1; color: white; } .save-button:hover { background-color: #3182ce; }
        input[type="number"] { width: 50px; padding: 4px; margin: 0 2px; border: 1px solid #cbd5e0; border-radius: 4px; text-align: center; }
        .ac-controls span { margin: 0 5px; }
    </style>
<script>
    async function fetchData() {
        try {
            const response = await fetch('/api/data');
            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            updateInterface(data);
        } catch (error) {
            console.error('Fetch Error:', error);
            document.getElementById('modbus-table-body').innerHTML = `<tr><td colspan="5">데이터 로드 실패: ${error.message}</td></tr>`;
        }
    }

    function updateInterface(data) {
        const tableBody = document.getElementById('modbus-table-body');
        let tableHTML = '';
        const units = [
            { id: 1, name: "유닛 1", dataKey: "_1" },
            { id: 2, name: "유닛 2", dataKey: "_2" }
        ];

        units.forEach(unit => {
            const temps = data[\`temperatures\${unit.dataKey}\`] || [];
            const highTs = data[\`high_thresholds\${unit.dataKey}\`] || [];
            const goodTs = data[\`good_thresholds\${unit.dataKey}\`] || [];
            const inputs = data[\`inputs\${unit.dataKey}\`] || [];

            for (let i = 0; i < 6; i++) { // 6 ACs per unit
                const temp = temps[i] ?? 'N/A';
                const status = typeof inputs[i] === 'boolean' ? (inputs[i] ? '🟢 ON' : '🔴 OFF') : 'N/A';
                const highT = highTs[i] ?? 27;
                const goodT = goodTs[i] ?? 20;
                const alertIcon = temp >= highT ? '🔥' : (temp <= goodT && !inputs[i] ? '❄️' : '');

                tableHTML += `
                    <tr>
                        <td>${unit.name} - 에어컨 ${i + 1}</td>
                        <td>${temp}°C ${alertIcon}</td>
                        <td>${status}</td>
                        <td class="ac-controls">
                            <button class="on-button" onclick="writeCoil(${unit.id}, ${i}, 1)">ON</button>
                            <button class="off-button" onclick="writeCoil(${unit.id}, ${i}, 0)">OFF</button>
                        </td>
                        <td>
                            <input type="number" id="u${unit.id}-ac${i}-high" value="${highT}" min="0" max="50">
                            <input type="number" id="u${unit.id}-ac${i}-good" value="${goodT}" min="0" max="50">
                            <button class="save-button" onclick="writeTempThreshold(${unit.id}, ${i})">저장</button>
                        </td>
                    </tr>`;
            }
        });
        tableBody.innerHTML = tableHTML;
    }

    async function writeCoil(unitId, acIndex, value) {
        try {
            const response = await fetch(`/api/write_coil?unitId=${unitId}&address=${acIndex}&value=${value}`, { method: 'POST' });
            const result = await response.json();
            if (result.error) alert("명령 실패: " + result.error);
            setTimeout(fetchData, 200);
        } catch (e) { alert("명령 전송 중 오류: " + e); }
    }

    async function writeTempThreshold(unitId, acIndex) {
        const highTemp = document.getElementById(`u${unitId}-ac${acIndex}-high`).value;
        const goodTemp = document.getElementById(`u${unitId}-ac${acIndex}-good`).value;

        if (parseInt(goodTemp) >= parseInt(highTemp)) {
            alert("하한 온도는 상한 온도보다 낮아야 합니다."); return;
        }
        if (parseInt(highTemp) > 50 || parseInt(highTemp) < 0 || parseInt(goodTemp) > 50 || parseInt(goodTemp) < 0) {
            alert("온도 설정은 0°C에서 50°C 사이여야 합니다."); return;
        }

        try {
            const response = await fetch(`/api/write_temp_threshold?unitId=${unitId}&acIndex=${acIndex}&highTemp=${highTemp}&goodTemp=${goodTemp}`, { method: 'POST' });
            const result = await response.json();
            if (result.error) {
                alert("설정 저장 실패: " + result.error);
            } else {
                // alert("설정 저장 완료"); // Optional feedback
                setTimeout(fetchData, 200);
            }
        } catch (e) { alert("설정 저장 중 오류: " + e); }
    }

    setInterval(fetchData, 2500);
    window.onload = fetchData;
</script>
</head>
<body>
    <h3>HVAC 개별 자동 온도 제어 시스템</h3>
    <table>
        <thead><tr><th>장치</th><th>현재 온도</th><th>상태</th><th>수동 명령</th><th>자동 온도 설정 (상한/하한 °C) & 저장</th></tr></thead>
        <tbody id="modbus-table-body"></tbody>
    </table>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
