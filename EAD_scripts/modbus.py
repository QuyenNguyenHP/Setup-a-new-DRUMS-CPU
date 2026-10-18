#Created by Duy Quyen - 29 Sep 2025


import asyncio
import traceback
import csv
import datetime
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusIOException
import struct

IMO_NO = "1114389"

CSV_LOG_PREFIX = "/home/drums/csv/EAD_NK_"
#CSV_LOG_PREFIX = "H429_"


ME_PORT_IP = "192.168.8.101"
ME_PORT_SLAVE_ID = 1
ME_PORT_Name = "ME_PORT"
ME_PORT_SerialNo = "DK636E0039"

ME_STBD_IP = "192.168.8.101"
ME_STBD_SLAVE_ID = 1
ME_STBD_Name = "ME_STBD"
ME_STBD_SerialNo = "DK636E0038"

DG1_IP = "192.168.8.105"
DG1_SLAVE_ID = 1
DG1_Name = "DG#1"
DG1_SerialNo = "DE618Z5178"

DG2_IP = "192.168.8.106"
DG2_SLAVE_ID = 2
DG2_Name = "DG#2"
DG2_SerialNo = "DE618Z4812"

DG3_IP = "192.168.8.107"
DG3_SLAVE_ID = 1
DG3_Name = "DG#3"
DG3_SerialNo = "DE618Z4863"

PMS_IP = "192.168.8.103"
PMS_SLAVE_ID = 3
PMS_Name = "PMS"
PMS_SerialNo = " "

TP_VALUES = {}

def decode_float32_from_registers(registers, index):
    if index + 1 >= len(registers):
        return None
    high = int(registers[index]) & 0xFFFF
    low = int(registers[index + 1]) & 0xFFFF
    return struct.unpack(">f", struct.pack(">HH", high, low))[0]



# ------------------- Read MODBUS DATAa & Write LOG CSV -------------------

async def read_modbus_data_DG(DG, slave_id, dg_name, imo, serial):
    try:
        flag = False
        dt = datetime.datetime.now()
        logfile = f"{CSV_LOG_PREFIX}{dg_name.replace('#','')}-{dt:%Y-%m-%d-%H-%M}.csv"

        with open(logfile, "a", newline="") as f:
            writer = csv.writer(f)

            # ========== ANALOG ==========
            print(f"\n✅ {dg_name} Analog Signal")
            analog_map = {
                #0x01: (f"{dg_name} FUEL OIL TEMPERATURE ENGINE INLET", "deg C", 1),
                #0x02: (f"{dg_name} BOOST AIR TEMPERATURE", "deg C", 1),
                0x03: (f"{dg_name} LUB OIL TEMPERATURE ENGINE INLET", "deg C", 1),
                0x04: (f"{dg_name} H.T. WATER TEMPERATURE ENGINE OUTLET", "deg C", 1),
                #0x05: (f"{dg_name} H.T. WATER TEMPERATURE ENGINE INLET", "deg C", 1),
                0x06: (f"{dg_name} No.1CYL. EXHAUST GAS TEMPERATURE", "deg C", 1),
                0x07: (f"{dg_name} No.2CYL. EXHAUST GAS TEMPERATURE", "deg C", 1),
                0x08: (f"{dg_name} No.3CYL. EXHAUST GAS TEMPERATURE", "deg C", 1),
                0x09: (f"{dg_name} No.4CYL. EXHAUST GAS TEMPERATURE", "deg C", 1),
                0x0A: (f"{dg_name} No.5CYL. EXHAUST GAS TEMPERATURE", "deg C", 1),
                0x0B: (f"{dg_name} No.6CYL. EXHAUST GAS TEMPERATURE", "deg C", 1),
                0x0E: (f"{dg_name} EXHAUST GAS TEMPERATURE T/C INLET 1", "deg C", 1),
                0x0F: (f"{dg_name} EXHAUST GAS TEMPERATURE T/C INLET 2", "deg C", 1),
                0x10: (f"{dg_name} EXHAUST GAS TEMPERATURE T/C OUTLET", "deg C", 1),
                0x11: (f"{dg_name} H.T. WATER PRESSURE ENGINE INLET", "MPa", 0.01),
                #0x12: (f"{dg_name} BOOST AIR PRESSURE", "MPa", 0.01),
                0x13: (f"{dg_name} L.T. WATER PRESSURE ENGINE INLET", "MPa", 0.01),
                0x14: (f"{dg_name} STARTING AIR PRESSURE", "MPa", 0.01),
                0x15: (f"{dg_name} FUEL OIL PRESSURE ENGINE INLET", "MPa", 0.01),
                #0x16: (f"{dg_name} CONTROL AIR PRESSURE", "MPa", 0.01),
                #0x17: (f"{dg_name} LO PRESS T/C INLET", "MPa", 0.01),
                #0x18: (f"{dg_name} LUB OIL FILTER DIFFERENTIAL PRESSURE", "MPa", 0.01),
                0x19: (f"{dg_name} LUB OIL PRESSURE", "MPa", 0.01),
                0x1A: (f"{dg_name} ENGINE SPEED", "min-1", 1),
                0x1C: (f"{dg_name} LOAD", "kW", 1),
                0x1D: (f"{dg_name} RUNNING HOUR", "x10Hours", 1),
                #0x21: (f"{dg_name} LUB. OIL TEMP. ENGINE OUTLET", "deg C", 1),
                #0x22: (f"{dg_name} L.T. WATER TEMP. ENGINE INLET", "deg C", 1),
                #0x23: (f"{dg_name} L.T. WATER TEMP. ENGINE OUTLET", "deg C", 1),
                #0x31: (f"{dg_name} T/C SPEED", "min-1", 1),
            }

            resp = await DG.read_input_registers(0x00, 35, slave=slave_id)
            if not resp.isError():
                for i, reg in enumerate(resp.registers):
                    addr = 0x00 + i
                    raw_val = int(reg)

                    if addr in analog_map:
                        label, unit, ratio = analog_map[addr]
                        val = raw_val * ratio

                        print(f"{label:<50}: {val} {unit}")
                        writer.writerow([
                            imo,
                            serial,
                            addr + 40000,
                            label,
                            dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                            val,
                            unit
                        ])

            else:
                print(f"❌ Error reading analog registers from {dg_name}")
                flag = True


            # ---------------- DISCRETE ----------------
            print(f"\n✅ {dg_name} Digital Signal")
            discrete_map = {
                0x01: (f"{dg_name} LUB OIL FILTER DIFFERENTIAL PRESSURE HIGH", "On/Off",),
                0x02: (f"{dg_name} CONTROL AIR PRESSURE LOW", "On/Off",),
                0x03: (f"{dg_name} FUEL OIL PRESSURE LOW", "On/Off",),
                0x04: (f"{dg_name} LUB OIL PRESSURE LOW", "On/Off",),
                0x05: (f"{dg_name} H.T. WATER PRESSURE LOW", "On/Off",),
                0x06: (f"{dg_name} L.T. WATER PRESSURE LOW", "On/Off",),
                0x07: (f"{dg_name} FUEL OIL DRAIN LEVEL HIGH", "On/Off",),
                0x08: (f"{dg_name} H.T. WATER TEMPERATURE HIGH", "On/Off",),
                0x09: (f"{dg_name} T/C LUB OIL PRESSURE LOW", "On/Off",),
                0x0A: (f"{dg_name} FUEL OIL FILTER DIFFERENTIAL PRESSURE HIGH", "On/Off",),
                0x0B: (f"{dg_name} STARTING AIR PRESSURE LOW", "On/Off",),
                0x0C: (f"{dg_name} FUEL OIL LEAK TANK LEVEL HIGH", "On/Off",),
                0x0D: (f"{dg_name} LUB OIL SUMP TANK LEVEL LOW", "On/Off",),
                0x0E: (f"{dg_name} LUB OIL SUMP TANK LEVEL HIGH", "On/Off",),
                0x0F: (f"{dg_name} OIL MIST PRE-ALARM", "On/Off",),
                0x10: (f"{dg_name} OIL MIST DETECTOR TROUBLE", "On/Off",),
                0x11: (f"{dg_name} ENGINE RUN", "On/Off",),
                0x12: (f"{dg_name} READY TO START", "On/Off",),
                0x13: (f"{dg_name} OVER SPEED (STOP)", "On/Off",),
                0x14: (f"{dg_name} H.T. WATER TEMPERATURE HIGH (STOP)", "On/Off",),
                0x15: (f"{dg_name} LUB OIL PRESSURE LOW (STOP)", "On/Off",),
                0x16: (f"{dg_name} OIL MIST HIGH DENSITY ALARM (STOP)", "On/Off",),
                0x17: (f"{dg_name} EMERGENCY STOP (REMOTE/LOCAL)", "On/Off",),
                0x18: (f"{dg_name} START FAILURE", "On/Off",),
                0x19: (f"{dg_name} PRIMING PUMP TERMAL FAILURE", "On/Off",),
                0x1A: (f"{dg_name} PRIMING LUB OIL PRESSURE LOW", "On/Off",),
                0x1B: (f"{dg_name} PRIMING PUMP RUN", "On/Off",),

                0x21: (f"{dg_name} SYSTEM FAILURE", "On/Off",),
                0x22: (f"{dg_name} CONTROL MODULE FAILURE", "On/Off",),
                0x23: (f"{dg_name} SAFTY MODULE FAILURE", "On/Off",),
                0x24: (f"{dg_name} LINK TO ENGINE CONDITION DISPLAY FAILURE", "On/Off",),
                0x25: (f"{dg_name} LINK TO REMOTE I/O 1 FAILURE", "On/Off",),
                0x26: (f"{dg_name} LINK TO REMOTE I/O 2 FAILURE", "On/Off",),
                0x27: (f"{dg_name} LINK TO LCD GAGE BOARD FAILURE", "On/Off",),

                0x29: (f"{dg_name} No.1 ALARM REPOSE SIGNAL(#14)", "On/Off",),
                0x2A: (f"{dg_name} No.2 ALARM REPOSE SIGNAL(#14T)", "On/Off",),
                0x2B: (f"{dg_name} No.3 ALARM REPOSE SIGNAL(EXH. GAS)", "On/Off",),
                0x2C: (f"{dg_name} No.4 ALARM REPOSE SIGNAL(PRIMING)", "On/Off",),
                0x2D: (f"{dg_name} No.5 ALARM REPOSE SIGNAL(STARTING)", "On/Off",),
                0x2E: (f"{dg_name} No.6 ALARM REPOSE SIGNAL(FILTER DIFF. PRESS.)", "On/Off",),

                0x31: (f"{dg_name} No.1CYL. EXH. GAS TEMP. DEVIATION ALARM", "On/Off",),
                0x32: (f"{dg_name} No.2CYL. EXH. GAS TEMP. DEVIATION ALARM", "On/Off",),
                0x33: (f"{dg_name} No.3CYL. EXH. GAS TEMP. DEVIATION ALARM", "On/Off",),
                0x34: (f"{dg_name} No.4CYL. EXH. GAS TEMP. DEVIATION ALARM", "On/Off",),
                0x35: (f"{dg_name} No.5CYL. EXH. GAS TEMP. DEVIATION ALARM", "On/Off",),
                0x36: (f"{dg_name} No.6CYL. EXH. GAS TEMP. DEVIATION ALARM", "On/Off",),

                0x39: (f"{dg_name} EXH. GAS TEMP. DEVIATION ALARM(COMMON)", "On/Off",),

                0x3B: (f"{dg_name} EMERGENCY STOP SWITCH OF EXT. (DISCONNECTION)", "On/Off",),
                0x3C: (f"{dg_name} EMERGENCY STOP SWITCH ON ECD (DISCONNECTION)", "On/Off",),
                0x3D: (f"{dg_name} H.T. WATER TEMP. HIGH SWITCH (DISCONNECTION)", "On/Off",),
                0x3E: (f"{dg_name} LUB OIL PRESS. LOW SWITCH (DISCONNECTION)", "On/Off",),
                0x3F: (f"{dg_name} OILMIST DETECTOR HIGH-ALARM (DISCONNECTION)", "On/Off",),
                0x40: (f"{dg_name} EMERGENCY STOP SOLENOID (DISCONNECTION)", "On/Off",),

                0x41: (f"{dg_name} FUEL OIL TEMP. ENGINE INLET SENSOR FAILURE", "On/Off",),
                0x42: (f"{dg_name} BOOST AIR TEMP. SENSOR FAILURE", "On/Off",),
                0x43: (f"{dg_name} LUB OIL TEMP. ENGINE INLET SENSOR FAILURE", "On/Off",),
                0x44: (f"{dg_name} H.T. WATER TEMP. ENGINE OUTLET SENSOR FAILURE", "On/Off",),
                0x45: (f"{dg_name} H.T. WATER TEMP. ENGINE INLET SENSOR FAILURE", "On/Off",),
                0x46: (f"{dg_name} No.1CYL. EXH. GAS TEMP. SENSOR FAILURE", "On/Off",),
                0x47: (f"{dg_name} No.2CYL. EXH. GAS TEMP. SENSOR FAILURE", "On/Off",),
                0x48: (f"{dg_name} No.3CYL. EXH. GAS TEMP. SENSOR FAILURE", "On/Off",),
                0x49: (f"{dg_name} No.4CYL. EXH. GAS TEMP. SENSOR FAILURE", "On/Off",),
                0x4A: (f"{dg_name} No.5CYL. EXH. GAS TEMP. SENSOR FAILURE", "On/Off",),
                0x4B: (f"{dg_name} No.6CYL. EXH. GAS TEMP. SENSOR FAILURE", "On/Off",),

                0x4E: (f"{dg_name} EXH. GAS TEMP. T/C INLET 1 SENSOR FAILURE", "On/Off",),
                0x4F: (f"{dg_name} EXH. GAS TEMP. T/C INLET 2 SENSOR FAILURE", "On/Off",),
                0x50: (f"{dg_name} EXH. GAS TEMP. T/C OUTLET SENSOR FAILURE", "On/Off",),

                0x51: (f"{dg_name} H.T. WATER PRESS. INLET SENSOR FAILURE", "On/Off",),
                0x52: (f"{dg_name} BOOST AIR PRESS. SENSOR FAILURE", "On/Off",),
                0x53: (f"{dg_name} L.T. WATER PRESS. INLET SENSOR FAILURE", "On/Off",),
                0x54: (f"{dg_name} STARTING AIR PRESS SENSOR FAILURE", "On/Off",),
                0x55: (f"{dg_name} FO PRESS INLET SENSOR FAILURE", "On/Off",),
                0x56: (f"{dg_name} CONTROL AIR PRESS SENSOR FAILURE", "On/Off",),
                0x57: (f"{dg_name} LO PRESS T/C INLET SENSOR FAILURE", "On/Off",),
                0x58: (f"{dg_name} LUB OIL FILTER DIFF. PRESS. SENSOR FAILURE", "On/Off",),
                0x59: (f"{dg_name} LUB OIL PRESSURE SENSOR FAILURE", "On/Off",),
                0x5A: (f"{dg_name} ALL SPEED PICKUP SENSOR FAILURE", "On/Off",),
                0x5B: (f"{dg_name} LOAD INPUT FAILURE", "On/Off",),

                0x71: (f"{dg_name} LUB OIL TEMP. ENGINE OUTLET SENSOR FAILURE", "On/Off",),
                0x72: (f"{dg_name} L.T. WATER TEMP. ENGINE INLET SENSOR FAILURE", "On/Off",),
                0x73: (f"{dg_name} L.T. WATER TEMP. ENGINE OUTLET SENSOR FAILURE", "On/Off",),
                0x81: (f"{dg_name} T/C SPEED SENSOR FAILURE", "On/Off",),
            }
            resp = await DG.read_discrete_inputs(0x00, 0x81, slave=slave_id)  # read 129 bits (0x00–0x80)
            if not resp.isError():
                for i, bit in enumerate(resp.bits):
                    addr = 0x00 + i
                    if addr in discrete_map:
                        label, unit = discrete_map[addr]
                        val = int(bit)
                        print(f"{label:<55}: {val}")
                        writer.writerow([
                            imo,
                            serial,
                            addr,
                            label,
                            dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                            val,
                            unit
                        ])
            else:
                print(f"❌ Error reading Digital registers from {dg_name}")
                flag = True
        if flag == False:
            print(f"\n=== ✅ WRITE {dg_name} DATA TO CSV SUCCESSFULLY")

    except Exception as e:
        print(f"❌ Error in read_modbus_data for {dg_name}: {e}")
        traceback.print_exc()
        await asyncio.sleep(0.1)

async def read_modbus_data_PORT(ME, slave_id, dg_name, imo, serial):
    try:
        flag =False
        dt = datetime.datetime.now()
        logfile = f"{CSV_LOG_PREFIX}{dg_name.replace('#','')}-{dt:%Y-%m-%d-%H-%M}.csv"
        with open(logfile, "a", newline="") as f:
            writer = csv.writer(f)

            # ========== ANALOG ==========
            print(f"\n✅ {dg_name} Analog Signal")
            analog_map = {
                0x01: (f"{dg_name} BOOST AIR PRESS.", "Mpa", 0.01),
                0x02: (f"{dg_name} FUEL OIL PRESS.", "Mpa", 0.01),
                0x03: (f"{dg_name} LUB. OIL PRESS.", "Mpa", 0.01),
                0x04: (f"{dg_name} H.T. F.W. PRESS.", "Mpa", 0.01),
                0x05: (f"{dg_name} T/C LUB. OIL PRESS.", "Mpa", 0.01),
                0x06: (f"{dg_name} L.O. AUTO. BACKWASH FILTER DIFF. P.", "Mpa", 0.01),

                0x07: (f"{dg_name} LUB. OIL TEMP.", "deg C", 1),
                0x08: (f"{dg_name} H.T. F.W. TEMP.", "deg C", 1),
                0x09: (f"{dg_name} BOOST AIR TEMP.", "deg C", 1),
                0x0A: (f"{dg_name} FUEL OIL TEMP.", "deg C", 1),

                0x0B: (f"{dg_name} NO.1 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x0C: (f"{dg_name} NO.2 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x0D: (f"{dg_name} NO.3 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x0E: (f"{dg_name} NO.4 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x0F: (f"{dg_name} NO.5 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x10: (f"{dg_name} NO.6 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),

                0x11: (f"{dg_name} EXH. GAS T/C INLET NO.1 TEMP.", "deg C", 1),
                0x12: (f"{dg_name} EXH. GAS T/C INLET NO.2 TEMP.", "deg C", 1),
                0x13: (f"{dg_name} EXH. GAS T/C OUTLET TEMP", "deg C", 1),

                0x14: (f"{dg_name} R/G OIL TEMP.", "deg C", 1),
                0x15: (f"{dg_name} R/G THRUST BEAR. TEMP.", "deg C", 1),

                0x2B: (f"{dg_name} NO.1 START AIR PRESS", "Mpa", 0.01),
                0x2C: (f"{dg_name} NO.2 START AIR PRESS", "Mpa", 0.01),
                0x2D: (f"{dg_name} CONTROL AIR PRESS.", "Mpa", 0.1),

                0x2F: (f"{dg_name} R/G LUB. OIL PRESS.", "Mpa", 0.01),

                0x32: (f"{dg_name} M/E REVOLUTION", "min-1", 1),
                0x33: (f"{dg_name} PROP. REVOLUTION", "Rpm", 1),
                0x34: (f"{dg_name} T/C REVOLUTION", "Rpm", 1),
                0x35: (f"{dg_name} F.O. RACK", "mm", 0.1),
            }

            resp = await ME.read_input_registers(0x00, 60, slave=slave_id)
            if not resp.isError():
                for i, reg in enumerate(resp.registers):
                    addr = 0x00 + i
                    raw_val = int(reg)

                    if addr in analog_map:
                        label, unit, ratio = analog_map[addr]
                        val = raw_val * ratio

                        print(f"{label:<50}: {val} {unit}")
                        writer.writerow([
                            imo,
                            serial,
                            addr + 40000,
                            label,
                            dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                            val,
                            unit
                        ])
            else:    
                print(f"❌ Error reading analog registers from {dg_name}")
                flag = True


            # ---------------- DISCRETE ----------------
            print(f"\n✅ {dg_name} Digital Signal")
            discrete_map = {
                0x01: (f"{dg_name} MAIN (AC) SOURCE", "On/Off"),
                0x02: (f"{dg_name} EMERG. (DC) SOURCE", "On/Off"),
                0x03: (f"{dg_name} TELEGRAPH SYSTEM SOURCE", "On/Off"),
                0x04: (f"{dg_name} GOVERNOR SOURCE", "On/Off"),
                0x05: (f"{dg_name} BATTERY SOURCE", "On/Off"),

                0x07: (f"{dg_name} CONTROL SYSTEM", "On/Off"),
                0x08: (f"{dg_name} SAFETY SYSTEM", "On/Off"),
                0x09: (f"{dg_name} GOVERNOR MAJOR FAILURE", "On/Off"),
                0x0A: (f"{dg_name} GOVERNOR MINOR FAILURE", "On/Off"),
                0x0B: (f"{dg_name} SPEED SW. UNIT FOR CONT. CPU", "On/Off"),
                0x0C: (f"{dg_name} SENSOR FOR CONTROL", "On/Off"),
                0x0D: (f"{dg_name} SPEED SW. UNIT FOR SAFETY CPU", "On/Off"),
                0x0E: (f"{dg_name} SENSOR FOR SAFETY", "On/Off"),
                0x0F: (f"{dg_name} HANDLE SWITCH", "On/Off"),

                0x12: (f"{dg_name} M/E MANUAL EMERG. SHUT DOWN", "On/Off"),
                0x13: (f"{dg_name} M/E OVER SPEED SHUT DOWN", "On/Off"),
                0x14: (f"{dg_name} M/E L.O. LOW PRESS. SHD", "On/Off"),
                0x15: (f"{dg_name} OIL MIST HIGH HIGH DENSITY SHD", "On/Off"),
                0x16: (f"{dg_name} R/G OPERATING OIL LOW PRESS. SHD", "On/Off"),
                0x17: (f"{dg_name} M/E EMERG. SHUT DOWN PREWARNING", "On/Off"),
                0x18: (f"{dg_name} M/E EMERG. SHUT DOWN CANCEL", "On/Off"),

                0x1A: (f"{dg_name} R/G OPERATING OIL LOW PRESS. SLD", "On/Off"),
                0x1B: (f"{dg_name} R/G OIL HIGH TEMP. SLD", "On/Off"),
                0x1C: (f"{dg_name} R/G THRUST BEAR. HIGH TEMP. SLD", "On/Off"),
                0x1D: (f"{dg_name} M/E SLOW DOWN PREWARNING", "On/Off"),
                0x1E: (f"{dg_name} M/E SLOW DOWN CANCEL", "On/Off"),

                0x20: (f"{dg_name} M/E FUEL OIL PRESS.", "On/Off"),
                0x21: (f"{dg_name} M/E LUB. OIL PRESS.", "On/Off"),
                0x22: (f"{dg_name} M/E H.T. F.W. PRESS.", "On/Off"),
                0x23: (f"{dg_name} M/E T/C LUB. OIL PRESS.", "On/Off"),
                0x24: (f"{dg_name} M/E FUEL OIL LEAKED TANK LEVEL", "On/Off"),
                0x25: (f"{dg_name} M/E L.O. AUTO. BACKWASH FILTER DIFF", "On/Off"),

                0x27: (f"{dg_name} M/E LUB. OIL TEMP.", "On/Off"),
                0x28: (f"{dg_name} M/E H.T. F.W. TEMP.", "On/Off"),

                0x2A: (f"{dg_name} M/E FUEL OIL TEMP.", "On/Off"),

                0x2C: (f"{dg_name} OIL MIST DETECTOR FAILURE", "On/Off"),
                0x2D: (f"{dg_name} OIL MIST HIGH DENSITY", "On/Off"),

                0x2E: (f"{dg_name} M/E NO.1 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x2F: (f"{dg_name} M/E NO.2 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x30: (f"{dg_name} M/E NO.3 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x31: (f"{dg_name} M/E NO.4 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x32: (f"{dg_name} M/E NO.5 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x33: (f"{dg_name} M/E NO.6 CYL. EXH. GAS OUTLET TEMP", "On/Off"),

                0x37: (f"{dg_name} M/E NO.1 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x38: (f"{dg_name} M/E NO.2 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x39: (f"{dg_name} M/E NO.3 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x3A: (f"{dg_name} M/E NO.4 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x3B: (f"{dg_name} M/E NO.5 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x3C: (f"{dg_name} M/E NO.6 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),

                0x3D: (f"{dg_name} NO.1 START AIR PRESS.(ALARM)", "On/Off"),
                0x3E: (f"{dg_name} NO.2 START AIR PRESS.(ALARM)", "On/Off"),
                0x3F: (f"{dg_name} CONTROL AIR PRESS.(ALARM)", "On/Off"),

                0x4C: (f"{dg_name} R/G LUB. OIL PRESS. (ALARM)", "On/Off"),
                0x4E: (f"{dg_name} R/G OIL TEMP. (ALARM)", "On/Off"),
                0x4F: (f"{dg_name} R/G THRUST BEAR. TEMP. (ALARM)", "On/Off"),

                0x51: (f"{dg_name} R/G OPERATING OIL LOW PRESS.", "On/Off"),
                0x52: (f"{dg_name} R/G L.O. FILTER HIGH DIFF. PRESS.", "On/Off"),
                0x53: (f"{dg_name} R/G OIL LEVEL TOO LOW", "On/Off"),
                0x54: (f"{dg_name} R/G CONTROL VOLTAGE", "On/Off"),
            }

            resp = await ME.read_discrete_inputs(0x00, 0x53, slave=slave_id)  # read 129 bits (0x00–0x80)
            if not resp.isError():
                for i, bit in enumerate(resp.bits):
                    addr = 0x00 + i
                    if addr in discrete_map:
                        label, unit = discrete_map[addr]
                        val = int(bit)
                        print(f"{label:<55}: {val}")
                        writer.writerow([
                            imo,
                            serial,
                            addr,
                            label,
                            dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                            val,
                            unit
                        ])
            else:
                print(f"❌ Error reading Digital registers from {dg_name}")
                flag = True
        if flag == False:
            print(f"\n=== ✅ WRITE {dg_name} DATA TO CSV SUCCESSFULLY")

    except Exception as e:
        print(f"❌ Error in read_modbus_data for {dg_name}: {e}")
        traceback.print_exc()
        await asyncio.sleep(0.1)
async def read_modbus_data_STBD(ME, slave_id, dg_name, imo, serial):
    try:
        flag = False
        dt = datetime.datetime.now()
        logfile = f"{CSV_LOG_PREFIX}{dg_name.replace('#','')}-{dt:%Y-%m-%d-%H-%M}.csv"

        with open(logfile, "a", newline="") as f:
            writer = csv.writer(f)

            # ========== ANALOG ==========
            print(f"\n✅ {dg_name} Analog Signal")
            analog_map = {
                0x16: (f"{dg_name} BOOST AIR PRESS.", "Mpa", 0.01),
                0x17: (f"{dg_name} FUEL OIL PRESS.", "Mpa", 0.01),
                0x18: (f"{dg_name} LUB. OIL PRESS.", "Mpa", 0.01),
                0x19: (f"{dg_name} H.T. F.W. PRESS.", "Mpa", 0.01),
                0x1A: (f"{dg_name} T/C LUB. OIL PRESS.", "Mpa", 0.01),
                0x1B: (f"{dg_name} L.O. AUTO. BACKWASH FILTER DIFF. P.", "Mpa", 0.01),

                0x1C: (f"{dg_name} LUB. OIL TEMP.", "deg C", 1),
                0x1D: (f"{dg_name} H.T. F.W. TEMP.", "deg C", 1),
                0x1E: (f"{dg_name} BOOST AIR TEMP.", "deg C", 1),
                0x1F: (f"{dg_name} FUEL OIL TEMP.", "deg C", 1),

                0x20: (f"{dg_name} NO.1 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x21: (f"{dg_name} NO.2 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x22: (f"{dg_name} NO.3 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x23: (f"{dg_name} NO.4 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x24: (f"{dg_name} NO.5 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),
                0x25: (f"{dg_name} NO.6 CYL. EXH. GAS OUTLET TEMP.", "deg C", 1),

                0x26: (f"{dg_name} EXH. GAS T/C INLET NO.1 TEMP.", "deg C", 1),
                0x27: (f"{dg_name} EXH. GAS T/C INLET NO.2 TEMP.", "deg C", 1),
                0x28: (f"{dg_name} EXH. GAS T/C OUTLET TEMP", "deg C", 1),

                0x29: (f"{dg_name} R/G OIL TEMP.", "deg C", 1),
                0x2A: (f"{dg_name} R/G THRUST BEAR. TEMP.", "deg C", 1),
                0x2B: (f"{dg_name} NO.1 START AIR PRESS", "Mpa", 0.01),
                0x2C: (f"{dg_name} NO.2 START AIR PRESS", "Mpa", 0.01),
                0x2D: (f"{dg_name} CONTROL AIR PRESS.", "Mpa", 0.1),
                0x30: (f"{dg_name} R/G LUB. OIL PRESS.", "Mpa", 0.01),

                0x37: (f"{dg_name} M/E REVOLUTION", "min-1", 1),
                0x38: (f"{dg_name} PROP. REVOLUTION", "Rpm", 1),
                0x39: (f"{dg_name} T/C REVOLUTION", "Rpm", 1),
                0x3A: (f"{dg_name} F.O. RACK", "mm", 0.1),
            }


            resp = await ME.read_input_registers(0x00, 0x3B,slave=slave_id)
            if not resp.isError():
                for i, reg in enumerate(resp.registers):
                    addr = 0x00 + i
                    raw_val = int(reg)
                    if addr in analog_map:
                        label, unit, ratio = analog_map[addr]
                        val = raw_val * ratio
                        print(f"{label:<50}: {val} {unit}")
                        writer.writerow([
                            imo,
                            serial,
                            addr + 40000,
                            label,
                            dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                            val,
                            unit
                        ])

            else:
                print(f"❌ Error reading analog registers from {dg_name}")
                flag = True


            # ---------------- DISCRETE ----------------
            print(f"\n✅ {dg_name} Digital Signal")
            discrete_map = {

                0x3D: (f"{dg_name} NO.1 START AIR PRESS.(ALARM)", "On/Off"),
                0x3E: (f"{dg_name} NO.2 START AIR PRESS.(ALARM)", "On/Off"),
                0x3F: (f"{dg_name} CONTROL AIR PRESS.(ALARM)", "On/Off"),

                0x5B: (f"{dg_name} MAIN (AC) SOURCE", "On/Off"),
                0x5C: (f"{dg_name} EMERG. (DC) SOURCE", "On/Off"),
                0x5D: (f"{dg_name} TELEGRAPH SYSTEM SOURCE", "On/Off"),
                0x5E: (f"{dg_name} GOVERNOR SOURCE", "On/Off"),
                0x5F: (f"{dg_name} BATTERY SOURCE", "On/Off"),

                0x61: (f"{dg_name} CONTROL SYSTEM", "On/Off"),
                0x62: (f"{dg_name} SAFETY SYSTEM", "On/Off"),
                0x63: (f"{dg_name} GOVERNOR MAJOR FAILURE", "On/Off"),
                0x64: (f"{dg_name} GOVERNOR MINOR FAILURE", "On/Off"),
                0x65: (f"{dg_name} SPEED SW. UNIT FOR CONT. CPU", "On/Off"),
                0x66: (f"{dg_name} SENSOR FOR CONTROL", "On/Off"),
                0x67: (f"{dg_name} SPEED SW. UNIT FOR SAFETY CPU", "On/Off"),
                0x68: (f"{dg_name} SENSOR FOR SAFETY", "On/Off"),
                0x69: (f"{dg_name} HANDLE SWITCH", "On/Off"),

                0x6C: (f"{dg_name} M/E MANUAL EMERG. SHUT DOWN", "On/Off"),
                0x6D: (f"{dg_name} M/E OVER SPEED SHUT DOWN", "On/Off"),
                0x6E: (f"{dg_name} M/E L.O. LOW PRESS. SHD", "On/Off"),
                0x6F: (f"{dg_name} OIL MIST HIGH HIGH DENSITY SHD", "On/Off"),
                0x70: (f"{dg_name} R/G OPERATING OIL LOW PRESS. SHD", "On/Off"),
                0x71: (f"{dg_name} M/E EMERG. SHUT DOWN PREWARNING", "On/Off"),
                0x72: (f"{dg_name} M/E EMERG. SHUT DOWN CANCEL", "On/Off"),

                0x74: (f"{dg_name} R/G OPERATING OIL LOW PRESS. SLD", "On/Off"),
                0x75: (f"{dg_name} R/G OIL HIGH TEMP. SLD", "On/Off"),
                0x76: (f"{dg_name} R/G THRUST BEAR. HIGH TEMP. SLD", "On/Off"),
                0x77: (f"{dg_name} M/E SLOW DOWN PREWARNING", "On/Off"),
                0x78: (f"{dg_name} M/E SLOW DOWN CANCEL", "On/Off"),

                0x7A: (f"{dg_name} M/E FUEL OIL PRESS.", "On/Off"),
                0x7B: (f"{dg_name} M/E LUB. OIL PRESS.", "On/Off"),
                0x7C: (f"{dg_name} M/E H.T. F.W. PRESS.", "On/Off"),
                0x7D: (f"{dg_name} M/E T/C LUB. OIL PRESS.", "On/Off"),
                0x7E: (f"{dg_name} M/E FUEL OIL LEAKED TANK LEVEL", "On/Off"),
                0x7F: (f"{dg_name} M/E L.O. AUTO. BACKWASH FILTER DIFF", "On/Off"),

                0x81: (f"{dg_name} M/E LUB. OIL TEMP.", "On/Off"),
                0x82: (f"{dg_name} M/E H.T. F.W. TEMP.", "On/Off"),

                0x84: (f"{dg_name} M/E FUEL OIL TEMP.", "On/Off"),

                0x86: (f"{dg_name} OIL MIST DETECTOR FAILURE", "On/Off"),
                0x87: (f"{dg_name} OIL MIST HIGH DENSITY", "On/Off"),

                0x88: (f"{dg_name} M/E NO.1 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x89: (f"{dg_name} M/E NO.2 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x8A: (f"{dg_name} M/E NO.3 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x8B: (f"{dg_name} M/E NO.4 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x8C: (f"{dg_name} M/E NO.5 CYL. EXH. GAS OUTLET TEMP", "On/Off"),
                0x8D: (f"{dg_name} M/E NO.6 CYL. EXH. GAS OUTLET TEMP", "On/Off"),

                0x91: (f"{dg_name} M/E NO.1 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x92: (f"{dg_name} M/E NO.2 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x93: (f"{dg_name} M/E NO.3 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x94: (f"{dg_name} M/E NO.4 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x95: (f"{dg_name} M/E NO.5 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),
                0x96: (f"{dg_name} M/E NO.6 CYL. EXH. GAS OUT. TEMP. DI", "On/Off"),

                0xA6: (f"{dg_name} R/G LUB. OIL PRESS. (ALARM)", "On/Off"),
                0xA8: (f"{dg_name} R/G OIL TEMP. (ALARM)", "On/Off"),
                0xA9: (f"{dg_name} R/G THRUST BEAR. TEMP. (ALARM)", "On/Off"),
                0xAB: (f"{dg_name} R/G OPERATING OIL LOW PRESS.", "On/Off"),
                0xAC: (f"{dg_name} R/G L.O. FILTER HIGH DIFF. PRESS.", "On/Off"),
                0xAD: (f"{dg_name} R/G OIL LEVEL TOO LOW", "On/Off"),
                0xAE: (f"{dg_name} R/G CONTROL VOLTAGE", "On/Off"),
            }


            resp = await ME.read_discrete_inputs(0x00,0xAD, slave=slave_id)  # read 129 bits (0x00–0x80)
            if not resp.isError():
                for i, bit in enumerate(resp.bits):
                    addr = 0x00 + i
                    if addr in discrete_map:
                        label, unit = discrete_map[addr]
                        val = int(bit)
                        print(f"{label:<55}: {val}")
                        writer.writerow([
                            imo,
                            serial,
                            addr,
                            label,
                            dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                            val,
                            unit
                        ])
            else:
                print(f"❌ Error reading Digital registers from {dg_name}")
                flag = True
        if flag == False:
            print(f"\n=== ✅ WRITE {dg_name} DATA TO CSV SUCCESSFULLY")

    except Exception as e:
        print(f"❌ Error in read_modbus_data for {dg_name}: {e}")
        traceback.print_exc()
        await asyncio.sleep(0.1)

async def read_modbus_data_PMS(PMS, slave_id, dg_name, imo):
    try:
        flag = False
        dt = datetime.datetime.now()
        logfile = f"{CSV_LOG_PREFIX}{dg_name.replace('#','')}-{dt:%Y-%m-%d-%H-%M}.csv"

        with open(logfile, "a", newline="") as f:
            writer = csv.writer(f)

            # ========== ANALOG ==========
            print(f"\n{dg_name} Analog Signal")
            
            PMS_map = {
                0x0B: (f"{dg_name} DG#1 CURRENT",       "A",  DG1_SerialNo, 32, 1),
                0x13: (f"{dg_name} DG#1 VOLTAGE",       "V",  DG1_SerialNo, 32, 1),
                0x1D: (f"{dg_name} DG#1 kW",            "kW", DG1_SerialNo, 32, 1),
                0x1F: (f"{dg_name} DG#1 POWER FACTOR",  "",   DG1_SerialNo, 16, 0.001),
                0x21: (f"{dg_name} DG#1 FREQUENCY",     "Hz", DG1_SerialNo, 32, 1),

                0x2D: (f"{dg_name} DG#2 CURRENT",       "A",  DG2_SerialNo, 32, 1),
                0x35: (f"{dg_name} DG#2 VOLTAGE",       "V",  DG2_SerialNo, 32, 1),
                0x3F: (f"{dg_name} DG#2 kW",            "kW", DG2_SerialNo, 32, 1),
                0x41: (f"{dg_name} DG#2 POWER FACTOR",  "",   DG2_SerialNo, 16, 0.001),
                0x43: (f"{dg_name} DG#2 FREQUENCY",     "Hz", DG2_SerialNo, 32, 1),

                0x4F: (f"{dg_name} DG#3 CURRENT",       "A",  DG3_SerialNo, 32, 1),
                0x57: (f"{dg_name} DG#3 VOLTAGE",       "V",  DG3_SerialNo, 32, 1),
                0x61: (f"{dg_name} DG#3 kW",            "kW", DG3_SerialNo, 32, 1),
                0x63: (f"{dg_name} DG#3 POWER FACTOR",  "",   DG3_SerialNo, 16, 0.001),
                0x65: (f"{dg_name} DG#3 FREQUENCY",     "Hz", DG3_SerialNo, 32, 1),
            }

            resp = await PMS.read_input_registers(0x00, 0x68, slave=slave_id)
            if not resp.isError():
                for addr in sorted(PMS_map):
                    label, unit, serial, bits, ratio = PMS_map[addr]

                    if bits == 32:
                        val = decode_float32_from_registers(resp.registers, addr)
                    else:  # 16-bit
                        val = resp.registers[addr]

                    if val is None:
                        continue
                    #val = round(val)
                    val *= ratio  # ✅ apply scaling
                    print(f"{label:<50}: {val} {unit}")
                    writer.writerow([
                        imo,
                        serial,
                        addr + 40000,
                        label,
                        dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                        val,
                        unit
                    ])


            else:
                print(f"Error reading analog registers from {dg_name}")
                flag = True
        if flag == False:
            print(f"\n=== WRITE {dg_name} DATA TO CSV SUCCESSFULLY")

    except Exception as e:
        print(f"??O Error in read_modbus_data for {dg_name}: {e}")
        traceback.print_exc()
        await asyncio.sleep(0.1)

# ------------------- Client -------------------
async def connect_client(client, address, retries=2, timeout=2, delay=1):
    """
    Try to connect to a client with limited retries.
    Returns True if connected, False if not.
    """
    for attempt in range(1, retries + 1):
        print(f"🔌 Connecting to {address} (try {attempt}/{retries})...")
        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
        except asyncio.TimeoutError:
            print(f"⏳ Timeout: {address} didn’t respond in {timeout}s")
        except Exception as e:
            print(f"❌ Connect error to {address}: {e}")

        if client.connected:
            print(f"✅ Connected {address}")
            return True

        await asyncio.sleep(delay)  # wait before retry

    print(f"⚠ Could not connect to {address} after {retries} tries → skip")
    return False


async def monitor_connection(client, address, retries=2, timeout=3):
    """
    Monitor client connection in background.
    If disconnected, retry connect with backoff.
    """
    backoff = 1
    while True:
        if not client.connected:
            print(f"⚠ Lost {address}, reconnecting...")

            ok = await connect_client(client, address, retries=retries, timeout=timeout, delay=backoff)
            if not ok:
                backoff = min(backoff * 2, 30)  # exponential backoff up to 30s
            else:
                backoff = 1  # reset backoff if reconnected
        await asyncio.sleep(1)


async def main():
    # Initialize clients

    DG1 = AsyncModbusTcpClient(DG1_IP, timeout=5)
    DG2 = AsyncModbusTcpClient(DG2_IP, timeout=5)
    DG3 = AsyncModbusTcpClient(DG3_IP, timeout=5)
    ME_PORT = AsyncModbusTcpClient(ME_PORT_IP, timeout=5)
    ME_STBD = AsyncModbusTcpClient(ME_STBD_IP, timeout=5)
    PMS = AsyncModbusTcpClient(PMS_IP, timeout=5)

    clients = [
        (DG1, DG1_IP, read_modbus_data_DG, (DG1_SLAVE_ID, DG1_Name, IMO_NO, DG1_SerialNo)),
        (DG2, DG2_IP, read_modbus_data_DG, (DG2_SLAVE_ID, DG2_Name, IMO_NO, DG2_SerialNo)),
        (DG3, DG3_IP, read_modbus_data_DG, (DG3_SLAVE_ID, DG3_Name, IMO_NO, DG3_SerialNo)),
        (ME_PORT, ME_PORT_IP, read_modbus_data_PORT, (ME_PORT_SLAVE_ID, ME_PORT_Name, IMO_NO, ME_PORT_SerialNo)),
        (ME_STBD, ME_STBD_IP, read_modbus_data_STBD, (ME_STBD_SLAVE_ID, ME_STBD_Name, IMO_NO, ME_STBD_SerialNo)),
        (PMS, PMS_IP, read_modbus_data_PMS, (PMS_SLAVE_ID, PMS_Name, IMO_NO)),
    ]

    try:
        # Initialize monitor
        active_clients = []
        for client, ip, _, _ in clients:
            if await connect_client(client, ip):
                asyncio.create_task(monitor_connection(client, ip))
                active_clients.append((client, ip))

        # Read data
        while True:
            for client, ip, reader_func, args in clients:
                if client.connected:
                    try:
                        await reader_func(client, *args)
                    except Exception as e:
                        print(f"Error reading {ip}: {e}")
                        traceback.print_exc()
            print("\n=== ✅ WAITING 30s ===")
            await asyncio.sleep(30)

    finally:
        print("🔻 Closing clients...")
        for client, _, _, _ in clients:
            await client.close()
        print("✅ All clients closed.")


if __name__ == "__main__":
    asyncio.run(main())
