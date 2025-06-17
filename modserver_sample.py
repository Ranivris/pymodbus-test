# final_server_6reg.py

import logging
import threading
import time
from pymodbus.datastore import (ModbusSequentialDataBlock, ModbusServerContext,
                                ModbusSlaveContext)
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.server import StartTcpServer

logging.basicConfig()
log = logging.getLogger()
log.setLevel(logging.INFO)

data_lock = threading.Lock()

# [수정] 모든 데이터 블록의 크기를 6으로 변경
db1_hr = ModbusSequentialDataBlock(0, [15] * 6)
db1_co = ModbusSequentialDataBlock(0, [False] * 6)
db1_di = ModbusSequentialDataBlock(0, [False] * 6)

db2_hr = ModbusSequentialDataBlock(0, [15] * 6)
db2_co = ModbusSequentialDataBlock(0, [False] * 6)
db2_di = ModbusSequentialDataBlock(0, [False] * 6)

context = ModbusServerContext(
    slaves={
        1: ModbusSlaveContext(di=db1_di, co=db1_co, hr=db1_hr),
        2: ModbusSlaveContext(di=db2_di, co=db2_co, hr=db2_hr),
    },
    single=False,
)

identity = ModbusDeviceIdentification()
identity.VendorName = 'Gemini 6-Reg Test'
identity.ProductName = '6-Register Test Server'

def update_discrete_inputs_thread(update_interval=0.5):
    datablocks = [{'co': db1_co, 'di': db1_di}, {'co': db2_co, 'di': db2_di}]
    while True:
        with data_lock:
            for db in datablocks:
                # [수정] 6개 읽기
                coil_vals = db['co'].getValues(0, count=6)
                db['di'].setValues(0, coil_vals)
        time.sleep(update_interval)

def update_temperature_thread(update_interval=2):
    datablocks = [{'hr': db1_hr, 'di': db1_di}, {'hr': db2_hr, 'di': db2_di}]
    while True:
        with data_lock:
            for db in datablocks:
                # [수정] 6개 읽기
                hr_vals = db['hr'].getValues(0, count=6)
                di_vals = db['di'].getValues(0, count=6)

                # [수정] 6개 확인
                if len(hr_vals) == 6 and len(di_vals) == 6:
                    # [수정] 6번 반복
                    for i in range(6):
                        if di_vals[i]:
                            if hr_vals[i] > 7: hr_vals[i] -= 1
                        else:
                            if hr_vals[i] < 30: hr_vals[i] += 1
                    db['hr'].setValues(0, hr_vals)
        time.sleep(update_interval)

def run_server():
    thread1 = threading.Thread(target=update_discrete_inputs_thread, daemon=True)
    thread2 = threading.Thread(target=update_temperature_thread, daemon=True)
    thread1.start()
    thread2.start()

    log.info(f"Modbus 서버 (6-레지스터 모드)를 시작합니다. 포트: 5020")
    StartTcpServer(context=context, identity=identity, address=("0.0.0.0", 5020))

if __name__ == "__main__":
    run_server()
