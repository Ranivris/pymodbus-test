# final_server_18reg_per_ac_auto_temp.py

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

# Holding registers per slave unit:
# - 6 for current temperatures (addrs 0-5)
# - 6 for high_temperature thresholds (addrs 6-11)
# - 6 for good_temperature thresholds (addrs 12-17)
# Total = 18 registers

INITIAL_TEMPS = [15] * 6
INITIAL_HIGH_THRESHOLDS = [27] * 6
INITIAL_GOOD_THRESHOLDS = [20] * 6

db1_hr_initial_values = INITIAL_TEMPS + INITIAL_HIGH_THRESHOLDS + INITIAL_GOOD_THRESHOLDS
db2_hr_initial_values = INITIAL_TEMPS + INITIAL_HIGH_THRESHOLDS + INITIAL_GOOD_THRESHOLDS

db1_hr = ModbusSequentialDataBlock(0, db1_hr_initial_values) # 18 registers
db1_co = ModbusSequentialDataBlock(0, [False] * 6)          # 6 coils
db1_di = ModbusSequentialDataBlock(0, [False] * 6)          # 6 discrete inputs

db2_hr = ModbusSequentialDataBlock(0, db2_hr_initial_values) # 18 registers
db2_co = ModbusSequentialDataBlock(0, [False] * 6)          # 6 coils
db2_di = ModbusSequentialDataBlock(0, [False] * 6)          # 6 discrete inputs

context = ModbusServerContext(
    slaves={
        1: ModbusSlaveContext(di=db1_di, co=db1_co, hr=db1_hr),
        2: ModbusSlaveContext(di=db2_di, co=db2_co, hr=db2_hr),
    },
    single=False,
)

identity = ModbusDeviceIdentification()
identity.VendorName = 'Gemini 18-Reg Per-AC AutoTemp'
identity.ProductName = '18-Register Per-AC AutoTemp Server'

def update_discrete_inputs_thread(update_interval=0.5):
    datablocks_config = [{'co_block': db1_co, 'di_block': db1_di}, {'co_block': db2_co, 'di_block': db2_di}]
    while True:
        with data_lock:
            for db_set in datablocks_config:
                coil_vals = db_set['co_block'].getValues(0, count=6)
                db_set['di_block'].setValues(0, coil_vals)
        time.sleep(update_interval)

def update_temperature_and_coils_thread(update_interval=0.5):
    datablocks_config = [
        {'hr_block': db1_hr, 'co_block': db1_co},
        {'hr_block': db2_hr, 'co_block': db2_co}
    ]
    while True:
        with data_lock:
            for db_set in datablocks_config:
                hr_block = db_set['hr_block']
                co_block = db_set['co_block']

                # Read all 18 holding registers
                hr_all_vals = hr_block.getValues(0, count=18)
                current_temperatures = hr_all_vals[0:6]
                high_temp_thresholds = hr_all_vals[6:12]
                good_temp_thresholds = hr_all_vals[12:18]

                _current_coils_for_deadband = co_block.getValues(0, count=6)
                new_coil_statuses = list(_current_coils_for_deadband)

                # Automatic Control Logic for each AC
                for i in range(6):
                    if current_temperatures[i] > high_temp_thresholds[i]:
                        new_coil_statuses[i] = True  # Turn AC ON
                    elif current_temperatures[i] < good_temp_thresholds[i]:
                        new_coil_statuses[i] = False  # Turn AC OFF
                    # Else: coil status remains as per _current_coils_for_deadband (manual override respected in deadband)

                co_block.setValues(0, new_coil_statuses)

                # Temperature Simulation Logic (based on new coil statuses)
                simulated_temperatures = list(current_temperatures)
                for i in range(6):
                    if new_coil_statuses[i]:  # AC is ON
                        if simulated_temperatures[i] > 7: # Min temp
                            simulated_temperatures[i] -= 1
                    else:  # AC is OFF
                        if simulated_temperatures[i] < 30: # Max temp
                            simulated_temperatures[i] += 1

                # Update all 18 holding registers
                # (updated temperatures + original individual thresholds)
                updated_hr_values = simulated_temperatures + high_temp_thresholds + good_temp_thresholds
                hr_block.setValues(0, updated_hr_values)

        time.sleep(update_interval)

def run_server():
    thread_di_update = threading.Thread(target=update_discrete_inputs_thread, daemon=True)
    thread_temp_coil_update = threading.Thread(target=update_temperature_and_coils_thread, args=(0.5,), daemon=True)

    thread_di_update.start()
    thread_temp_coil_update.start()

    log.info(f"Modbus 서버 (18-레지스터, 개별 AC 자동온도조절 모드)를 시작합니다. 포트: 5020")
    StartTcpServer(context=context, identity=identity, address=("0.0.0.0", 5020))

if __name__ == "__main__":
    run_server()
