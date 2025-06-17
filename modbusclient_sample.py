from flask import Flask, jsonify, render_template_string, request
from pymodbus.client import ModbusTcpClient
import logging

log = logging.getLogger('modbus_client_app')
log.setLevel(logging.DEBUG) # Set overall level to DEBUG to catch debug messages

if not log.handlers:
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    stream_handler.setFormatter(formatter)
    log.addHandler(stream_handler)

first_api_data_call = True

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
        log.debug(f"Reading from unit {unit_id}, FC {fc}, addr {address}, count {count}")
        response = func(address, count=count, slave=unit_id)
        if response.isError():
            log.warning(f"Modbus error from unit {unit_id}, FC {fc}, addr {address}: {response}")
            return None, f"읽기 오류: {response}"
        return response.registers if fc == 3 else response.bits[:count], None
    except Exception as e:
        log.error(f"Modbus 통신 예외 unit {unit_id}, FC {fc}, addr {address}: {e}", exc_info=True)
        return None, f"Modbus 통신 예외: {e}"

def write_coil_register(client, unit_id, address, value):
    try:
        log.info(f"Writing coil to unit {unit_id}, addr {address}, value {value}")
        response = client.write_coil(address, value, slave=unit_id)
        if response.isError():
            log.warning(f"Modbus coil write error unit {unit_id}, addr {address}: {response}")
            return False, f"쓰기 오류: {response}"
        return True, None
    except Exception as e:
        log.error(f"Modbus coil write 통신 예외 unit {unit_id}, addr {address}: {e}", exc_info=True)
        return False, f"Modbus 통신 예외: {e}"

def write_single_holding_register(client, unit_id, address, value):
    try:
        log.info(f"Writing HR to unit {unit_id}, addr {address}, value {value}")
        response = client.write_register(address, value, slave=unit_id)
        if response.isError():
            log.warning(f"Modbus HR write error unit {unit_id}, addr {address}: {response}")
            return False, f"쓰기 오류: {response}"
        return True, None
    except Exception as e:
        log.error(f"Modbus HR write 통신 예외 unit {unit_id}, addr {address}: {e}", exc_info=True)
        return False, f"Modbus 통신 예외: {e}"

# --- Flask 라우트 ---
app = Flask(__name__)

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/api/data', methods=['GET'])
def get_data():
    global first_api_data_call
    if first_api_data_call:
        log.info("First call to /api/data, performing initial data read. Subsequent reads will be logged at DEBUG level by read_registers.")
        first_api_data_call = False
    else:
        # Ensuring this path also has a clear log, but perhaps less prominent than the 'first call'
        log.info("Request received for /api/data (subsequent call)")

    client = ModbusTcpClient("127.0.0.1", port=5020, timeout=2)
    if not client.connect():
        log.error("Failed to connect to Modbus server at 127.0.0.1:5020")
        return jsonify({"error": "Modbus 서버 연결 실패"}), 500
    try:
        hr1_all, err1_hr = read_registers(client, 1, 3, 0, 18)
        di1_status, err1_di = read_registers(client, 1, 2, 0, 6)
        hr2_all, err2_hr = read_registers(client, 2, 3, 0, 18)
        di2_status, err2_di = read_registers(client, 2, 2, 0, 6)

        errors = [e for e in [err1_hr, err1_di, err2_hr, err2_di] if e]
        if errors:
            log.warning(f"Modbus read errors encountered: {errors}")
            return jsonify({"error": f"데이터 읽기 중 오류 발생: {'; '.join(errors)}"}), 500

        def process_hr_data(hr_data, unit_num_for_log):
            if hr_data and len(hr_data) == 18:
                return hr_data[0:6], hr_data[6:12], hr_data[12:18]
            log.warning(f"Invalid hr_data for unit {unit_num_for_log} from Modbus: Length {len(hr_data) if hr_data else 'None'}. Using defaults.")
            return [15]*6, [27]*6, [20]*6

        temps1, high_T1, good_T1 = process_hr_data(hr1_all, 1)
        temps2, high_T2, good_T2 = process_hr_data(hr2_all, 2)

        def process_di_data(di_data, unit_num_for_log):
            if di_data and len(di_data) == 6:
                return di_data
            log.warning(f"Invalid di_data for unit {unit_num_for_log} from Modbus: Length {len(di_data) if di_data else 'None'}. Using defaults.")
            return [False]*6

        processed_di1_status = process_di_data(di1_status, 1)
        processed_di2_status = process_di_data(di2_status, 2)

        response_data = {
            "temperatures_1": temps1,
            "high_thresholds_1": high_T1,
            "good_thresholds_1": good_T1,
            "inputs_1": processed_di1_status,
            "temperatures_2": temps2,
            "high_thresholds_2": high_T2,
            "good_thresholds_2": good_T2,
            "inputs_2": processed_di2_status,
        }
        log.debug(f"Successfully processed data for /api/data. Sending to client.")
        return jsonify(response_data)
    except Exception as e:
        log.error(f"Exception in /api/data endpoint: {e}", exc_info=True)
        return jsonify({"error": "서버 내부 오류 발생"}), 500
    finally:
        client.close()

@app.route('/api/write_coil', methods=['POST'])
def set_coil():
    try:
        unit_id = int(request.args.get('unitId'))
        address = int(request.args.get('address'))
        value = bool(int(request.args.get('value')))
    except Exception as e:
        log.warning(f"Invalid parameters for /api/write_coil: {request.args}, error: {e}")
        return jsonify({"error": "잘못된 파라미터 (코일)"}), 400

    log.info(f"Request to /api/write_coil: unit={unit_id}, ac_idx/addr={address}, value={value}")
    client = ModbusTcpClient("127.0.0.1", port=5020, timeout=2)
    if not client.connect():
        log.error("Failed to connect to Modbus server for write_coil")
        return jsonify({"error": "Modbus 서버 연결 실패"}), 500
    try:
        success, error = write_coil_register(client, unit_id, address, value)
        if success:
            log.info(f"Successfully processed /api/write_coil for unit {unit_id}, addr {address}")
            return jsonify({"success": True})
        else:
            log.warning(f"Failed to process /api/write_coil for unit {unit_id}, addr {address}: {error}")
            return jsonify({"error": error}), 500
    except Exception as e:
        log.error(f"Exception in /api/write_coil: {e}", exc_info=True)
        return jsonify({"error": "코일 쓰기 중 서버 내부 오류"}), 500
    finally: client.close()

@app.route('/api/write_temp_threshold', methods=['POST'])
def set_temp_threshold():
    try:
        unit_id = int(request.args.get('unitId'))
        ac_index = int(request.args.get('acIndex'))
        high_temp = int(request.args.get('highTemp'))
        good_temp = int(request.args.get('goodTemp'))

        if not (0 <= ac_index <= 5):
            log.warning(f"Invalid ac_index in /api/write_temp_threshold: {ac_index}")
            return jsonify({"error": "잘못된 AC 인덱스입니다."}), 400
        if not (0 <= high_temp <= 50 and 0 <= good_temp <= 50 and good_temp < high_temp):
            log.warning(f"Invalid temp values in /api/write_temp_threshold: high={high_temp}, good={good_temp}")
            return jsonify({"error": "잘못된 온도 설정 값입니다."}), 400
    except Exception as e:
        log.warning(f"Invalid parameters for /api/write_temp_threshold: {request.args}, error: {e}")
        return jsonify({"error": "잘못된 파라미터 (온도 임계값)"}), 400

    log.info(f"Request to /api/write_temp_threshold: unit={unit_id}, ac_idx={ac_index}, high={high_temp}, good={good_temp}")
    client = ModbusTcpClient("127.0.0.1", port=5020, timeout=2)
    if not client.connect():
        log.error("Failed to connect to Modbus server for write_temp_threshold")
        return jsonify({"error": "Modbus 서버 연결 실패"}), 500
    try:
        addr_high_T = 6 + ac_index
        addr_good_T = 12 + ac_index

        success1, error1 = write_single_holding_register(client, unit_id, addr_high_T, high_temp)
        if not success1:
            log.warning(f"Failed to write high_temp for unit {unit_id}, ac_idx {ac_index}: {error1}")
            return jsonify({"error": f"상한 온도 쓰기 실패: {error1}"}), 500

        success2, error2 = write_single_holding_register(client, unit_id, addr_good_T, good_temp)
        if not success2:
            log.warning(f"Failed to write good_temp for unit {unit_id}, ac_idx {ac_index}: {error2}")
            return jsonify({"error": f"하한 온도 쓰기 실패: {error2}"}), 500

        log.info(f"Successfully processed /api/write_temp_threshold for unit {unit_id}, ac_idx {ac_index}")
        return jsonify({"success": True}), 200
    except Exception as e:
        log.error(f"Exception in /api/write_temp_threshold: {e}", exc_info=True)
        return jsonify({"error": "임계값 쓰기 중 서버 내부 오류"}), 500
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
            console.log("Fetching /api/data...");
            const response = await fetch('/api/data');
            console.log("Response status:", response.status, response.statusText);
            if (!response.ok) {
                const errorText = await response.text().catch(() => "Failed to get error text");
                throw new Error(`Server error: ${response.status} ${response.statusText}. Response: ${errorText}`);
            }
            const data = await response.json();
            console.log("Data received from /api/data:", JSON.stringify(data, null, 2));
            if (data.error) {
                throw new Error(`API returned error: ${data.error}`);
            }
            updateInterface(data);
        } catch (error) {
            console.error('Fetch Error Details:', error);
            const tableBody = document.getElementById('modbus-table-body');
            if (tableBody) {
                tableBody.innerHTML = `<tr><td colspan="5">데이터 로드 실패: ${error.message.replace(/\n/g, '<br>')}</td></tr>`;
            } else {
                console.error("Could not find 'modbus-table-body' to display error.");
            }
        }
    }

    function updateInterface(data) {
        try {
            const tableBody = document.getElementById('modbus-table-body');
            if (!tableBody) {
                console.error("'modbus-table-body' not found in updateInterface.");
                return;
            }
            let tableHTML = '';
            const units = [
                { id: 1, name: "유닛 1", dataKey: "_1" },
                { id: 2, name: "유닛 2", dataKey: "_2" }
            ];

            console.log("Attempting to update interface with data:", JSON.stringify(data, null, 2));

            units.forEach(unit => {
                const temps = data[`temperatures${unit.dataKey}`] || [];
                const highTs = data[`high_thresholds${unit.dataKey}`] || [];
                const goodTs = data[`good_thresholds${unit.dataKey}`] || [];
                const inputs = data[`inputs${unit.dataKey}`] || [];

                console.log(`Processing Unit ${unit.id}: Temps(${temps.length}), HighTs(${highTs.length}), GoodTs(${goodTs.length}), Inputs(${inputs.length})`);

                for (let i = 0; i < 6; i++) {
                    const temp = temps[i] ?? 'N/A';
                    const status = typeof inputs[i] === 'boolean' ? (inputs[i] ? '🟢 ON' : '🔴 OFF') : 'N/A';
                    const highT = highTs[i] ?? 27;
                    const goodT = goodTs[i] ?? 20;
                    const alertIcon = temp !== 'N/A' && temp >= highT ? '🔥' : (temp !== 'N/A' && temp <= goodT && !inputs[i] ? '❄️' : '');

                    tableHTML += `
                        <tr>
                            <td>${unit.name} - 에어컨 ${i + 1}</td>
                            <td>${temp}${temp !== 'N/A' ? '°C' : ''} ${alertIcon}</td>
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

            if (tableHTML === '') {
                console.warn("tableHTML is empty after processing units. This will result in an empty table.");
                tableBody.innerHTML = `<tr><td colspan="5">표시할 데이터가 없습니다. 서버 응답을 확인하세요: ${JSON.stringify(data, null, 2)}</td></tr>`;
            } else {
                tableBody.innerHTML = tableHTML;
            }
            console.log("Interface update process complete.");
        } catch (e) {
            console.error("Error during updateInterface:", e);
            const tableBody = document.getElementById('modbus-table-body');
            if (tableBody) {
                 tableBody.innerHTML = `<tr><td colspan="5">UI 업데이트 중 오류 발생: ${e.message.replace(/\n/g, '<br>')}</td></tr>`;
            }
        }
    }

    async function writeCoil(unitId, acIndex, value) {
        try {
            console.log(`Writing coil: unitId=${unitId}, acIndex=${acIndex}, value=${value}`);
            const response = await fetch(`/api/write_coil?unitId=${unitId}&address=${acIndex}&value=${value}`, { method: 'POST' });
            const result = await response.json();
            console.log("Write coil response:", result);
            if (result.error) alert("명령 실패: " + result.error);
            setTimeout(fetchData, 200);
        } catch (e) {
            console.error("Error in writeCoil:", e);
            alert("명령 전송 중 오류: " + e.message);
        }
    }

    async function writeTempThreshold(unitId, acIndex) {
        const highTempElem = document.getElementById(`u${unitId}-ac${acIndex}-high`);
        const goodTempElem = document.getElementById(`u${unitId}-ac${acIndex}-good`);

        if (!highTempElem || !goodTempElem) {
            console.error(`Could not find input elements for u${unitId}-ac${acIndex}`);
            alert("UI 요소를 찾을 수 없습니다.");
            return;
        }
        const highTemp = highTempElem.value;
        const goodTemp = goodTempElem.value;

        console.log(`Writing temp threshold: unitId=${unitId}, acIndex=${acIndex}, highTemp=${highTemp}, goodTemp=${goodTemp}`);

        if (parseInt(goodTemp) >= parseInt(highTemp)) {
            alert("하한 온도는 상한 온도보다 낮아야 합니다."); return;
        }
        if (parseInt(highTemp) > 50 || parseInt(highTemp) < 0 || parseInt(goodTemp) > 50 || parseInt(goodTemp) < 0) {
            alert("온도 설정은 0°C에서 50°C 사이여야 합니다."); return;
        }

        try {
            const response = await fetch(`/api/write_temp_threshold?unitId=${unitId}&acIndex=${acIndex}&highTemp=${highTemp}&goodTemp=${goodTemp}`, { method: 'POST' });
            const result = await response.json();
            console.log("Write temp threshold response:", result);
            if (result.error) {
                alert("설정 저장 실패: " + result.error);
            } else {
                setTimeout(fetchData, 200);
            }
        } catch (e) {
            console.error("Error in writeTempThreshold:", e);
            alert("설정 저장 중 오류: " + e.message);
        }
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
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    log.info("Starting Flask app for Modbus client UI.")
    app.run(host="0.0.0.0", port=8000, debug=False)
