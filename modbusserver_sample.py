# modbusserver_sample.py

import logging
import threading
import time
from pymodbus.datastore import (ModbusSequentialDataBlock, ModbusServerContext,
                                ModbusSlaveContext)
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.server import StartTcpServer

logging.basicConfig(level=logging.DEBUG) # Ensure DEBUG level for all loggers
log = logging.getLogger('modbus_server_app')
# If modbus_server_app needs a different level than root, set it explicitly:
# log.setLevel(logging.DEBUG)

data_lock = threading.Lock()

NUM_AC_UNITS = 5
INITIAL_TEMPS = [15] * NUM_AC_UNITS
INITIAL_HIGH_THRESHOLDS = [27] * NUM_AC_UNITS
INITIAL_GOOD_THRESHOLDS = [20] * NUM_AC_UNITS
LAST_DUMMY_VALUE = [0xFE]

db1_hr_initial_values = INITIAL_TEMPS + INITIAL_HIGH_THRESHOLDS + INITIAL_GOOD_THRESHOLDS + LAST_DUMMY_VALUE
db2_hr_initial_values = INITIAL_TEMPS + INITIAL_HIGH_THRESHOLDS + INITIAL_GOOD_THRESHOLDS + LAST_DUMMY_VALUE

db1_hr = ModbusSequentialDataBlock(0, db1_hr_initial_values) # 16 registers
db1_co = ModbusSequentialDataBlock(0, [False] * NUM_AC_UNITS) # 5 coils
db1_di = ModbusSequentialDataBlock(0, [False] * NUM_AC_UNITS) # 5 discrete inputs

db2_hr = ModbusSequentialDataBlock(0, db2_hr_initial_values) # 16 registers
db2_co = ModbusSequentialDataBlock(0, [False] * NUM_AC_UNITS) # 5 coils
db2_di = ModbusSequentialDataBlock(0, [False] * NUM_AC_UNITS) # 5 discrete inputs

log.info(f"Initialized datastore for Unit 1: db1_hr length: {len(db1_hr.values)}, db1_co length: {len(db1_co.values)}, db1_di length: {len(db1_di.values)}")
log.info(f"Initialized datastore for Unit 2: db2_hr length: {len(db2_hr.values)}, db2_co length: {len(db2_co.values)}, db2_di length: {len(db2_di.values)}")

context = ModbusServerContext(
    slaves={
        1: ModbusSlaveContext(di=db1_di, co=db1_co, hr=db1_hr),
        2: ModbusSlaveContext(di=db2_di, co=db2_co, hr=db2_hr),
    },
    single=False,
)

identity = ModbusDeviceIdentification()
identity.VendorName = 'Gemini 16-Reg (5AC+Dummy) AutoTemp'
identity.ProductName = '16-Register AutoTemp Server (5ACs)'

def update_discrete_inputs_thread(update_interval=2): # Changed default to 2
    datablocks_config = [{'co_block': db1_co, 'di_block': db1_di}, {'co_block': db2_co, 'di_block': db2_di}]
    while True:
        with data_lock:
            for db_set in datablocks_config:
                coil_vals = db_set['co_block'].getValues(0, count=NUM_AC_UNITS)
                db_set['di_block'].setValues(0, coil_vals)
        time.sleep(update_interval)

def update_temperature_and_coils_thread(update_interval=2): # Changed default to 2
    datablocks_config = [
        {'hr_block': db1_hr, 'co_block': db1_co, 'unit_num': 1},
        {'hr_block': db2_hr, 'co_block': db2_co, 'unit_num': 2}
    ]
    while True:
        with data_lock:
            for db_set in datablocks_config:
                hr_block = db_set['hr_block']
                co_block = db_set['co_block']
                unit_num_for_log = db_set['unit_num']

                log.debug(f"[Unit {unit_num_for_log}] Update cycle. Current hr_block.values length: {len(hr_block.values)}")
                hr_all_vals = hr_block.getValues(0, count=16)
                log.debug(f"[Unit {unit_num_for_log}] Read hr_all_vals (requested count 16): {hr_all_vals} (Actual length: {len(hr_all_vals)})")

                if len(hr_all_vals) != 16:
                    log.error(f"[Unit {unit_num_for_log}] CRITICAL: Expected 16 HRs but read {len(hr_all_vals)}. Skipping update cycle for this unit.")
                    continue

                current_temperatures = hr_all_vals[0:NUM_AC_UNITS]
                high_temp_thresholds = hr_all_vals[NUM_AC_UNITS : NUM_AC_UNITS*2]
                good_temp_thresholds = hr_all_vals[NUM_AC_UNITS*2 : NUM_AC_UNITS*3]
                dummy_value = hr_all_vals[NUM_AC_UNITS*3]

                _current_coils_for_deadband = co_block.getValues(0, count=NUM_AC_UNITS)
                new_coil_statuses = list(_current_coils_for_deadband)

                for i in range(NUM_AC_UNITS):
                    if current_temperatures[i] > high_temp_thresholds[i]:
                        new_coil_statuses[i] = True
                    elif current_temperatures[i] < good_temp_thresholds[i]:
                        new_coil_statuses[i] = False

                co_block.setValues(0, new_coil_statuses)

                simulated_temperatures = list(current_temperatures)
                for i in range(NUM_AC_UNITS):
                    if new_coil_statuses[i]:
                        if simulated_temperatures[i] > 7:
                            simulated_temperatures[i] -= 1
                    else:
                        if simulated_temperatures[i] < 30:
                            simulated_temperatures[i] += 1

                log.debug(f"[Unit {unit_num_for_log}] Temps (before sim): {current_temperatures}, Coils: {new_coil_statuses} (len {len(new_coil_statuses)}), Temps (after sim): {simulated_temperatures}")
                log.debug(f"[Unit {unit_num_for_log}] Thresholds high: {high_temp_thresholds}, good: {good_temp_thresholds}, dummy: {dummy_value}")

                updated_hr_values = simulated_temperatures + high_temp_thresholds + good_temp_thresholds + [dummy_value]
                log.debug(f"[Unit {unit_num_for_log}] Writing updated_hr_values (len {len(updated_hr_values)}): {updated_hr_values}")
                hr_block.setValues(0, updated_hr_values)
                log.debug(f"[Unit {unit_num_for_log}] After setValues, hr_block.values: {hr_block.values[:16]}...")

        time.sleep(update_interval)

def run_server():
    thread_di_update = threading.Thread(target=update_discrete_inputs_thread, daemon=True)
    # Removed args, so it uses the new default interval of 2s from the function signature
    thread_temp_coil_update = threading.Thread(target=update_temperature_and_coils_thread, daemon=True)

    thread_di_update.start()
    thread_temp_coil_update.start()

    log.info(f"Modbus 서버 (16-레지스터, 5AC+Dummy, 2s update) 시작. 포트: 5020") # Updated log message
    StartTcpServer(context=context, identity=identity, address=("0.0.0.0", 5020))

if __name__ == "__main__":
    run_server()
