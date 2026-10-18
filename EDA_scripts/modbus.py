#Created by Duy Quyen - 29 Sep 2025
import asyncio
import traceback
import csv
import datetime
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusIOException

IMO_NO = "9982201"

DG1_IP = "192.168.100.11"
DG1_SLAVE_ID = 16
DG1_Name = "DG#1"
DG1_SerialNo = "DE618Z4585"

DG2_IP = "192.168.100.12"
DG2_SLAVE_ID = 16
DG2_Name = "DG#2"
DG2_SerialNo = "DE618Z4586"

DG3_IP = "192.168.100.13"
DG3_SLAVE_ID = 16
DG3_Name = "DG#3"
DG3_SerialNo = "DE618Z4587"

TP_VALUES = {}


# ------------------- Read MODBUS DATAa & Write LOG CSV -------------------

async def read_modbus_data(DG, slave_id, dg_name, imo, serial):
    flag = False
    """Read and process Modbus data of a DG (generic for DG#1, DG#2, DG#3...)."""
    try:

        dt = datetime.datetime.now()
        logfile = f"/home/drums/csv/EDA_NK_{dg_name.replace('#','')}-{dt:%Y-%m-%d-%H-%M}.csv"

        with open(logfile, "a", newline="") as f:
            writer = csv.writer(f)

            # --- Repose Inputs ---
            response = await DG.read_discrete_inputs(0x28, 6, slave=slave_id)
            print(f"\n✅ {dg_name} Repose Status")
            if not response.isError():
                for i, key in enumerate(["TP1a","TP2a","TP3a","TP4a","TP5a","TP6a"]):
                    TP_VALUES[key] = response.bits[i]
                    print(f"{dg_name} {key:<70}: {TP_VALUES[key]}")
                    #writer.writerow([imo, serial, key, dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"), TP_VALUES[key], "ON/OFF"])
            else:
                print(f"❌ Error reading Repose Status from {dg_name}")
                flag = True

            # ========== ANALOG ==========
            print(f"\n✅ {dg_name} Analog Signal")
            analog_map = {
                0x02: (f"{dg_name} Lub. oil temp. engine inlet", 65, ">=", "cc14", "deg C", 1),
                0x03: (f"{dg_name} High temp. cooling water temp. engine outlet", 90, ">=", "cc10", "deg C", 1),
                0x05: (f"{dg_name} No.1 cylinder exhaust gas temp.", 480, ">=", "cc1", "deg C", 1),
                0x06: (f"{dg_name} No.2 cylinder exhaust gas temp.", 480, ">=", "cc2", "deg C", 1),
                0x07: (f"{dg_name} No.3 cylinder exhaust gas temp.", 480, ">=", "cc3", "deg C", 1),
                0x08: (f"{dg_name} No.4 cylinder exhaust gas temp.", 480, ">=", "cc4", "deg C", 1),
                0x09: (f"{dg_name} No.5 cylinder exhaust gas temp.", 480, ">=", "cc5","deg C", 1),
                0x0A: (f"{dg_name} No.6 cylinder exhaust gas temp.", 480, ">=", "cc6", "deg C", 1),
                0x0D: (f"{dg_name} Exhaust gas temp. T/C inlet 1", 580, ">=", "cc7", "deg C", 1),
                0x0E: (f"{dg_name} Exhaust gas temp. T/C inlet 2", 580, ">=", "cc8", "deg C", 1),
                0x0F: (f"{dg_name} Exhaust gas temp. T/C outlet", 480, ">=", "cc9", "deg C", 1),
                0x10: (f"{dg_name} High temp. cooling water presure engine inlet", 15, "<=", "cc11", "MPa", 0.01),
                #0x11: (f"{dg_name} Boost air presure", 15, "<=", None, "MPa", 0.001),Fuel oil pressure engine inlet
                0x12: (f"{dg_name} Low temp. cooling water presure engine inlet", 15, "<=", "cc12", "MPa", 0.01),
                0x13: (f"{dg_name} Starting air pressure", 150, "<=", "cc16", "MPa", 0.01),
                0x14: (f"{dg_name} Fuel oil pressure engine inlet", 35, "<=", "cc15", "MPa", 0.01),
                #0x17: (f"{dg_name} Lub. oil filter differential", 2, "<=", None, "MPa", 0.01),
                0x18: (f"{dg_name} Lub. oil pressure", 35, "<=", "cc13", "MPa", 0.01),
                0x19: (f"{dg_name} Engine speed", 1020, ">=", "cc17", "min-1", 1),
                0x1B: (f"{dg_name} Load", None, None, None, "kW", 1),
                0x1C: (f"{dg_name} Running hour", None, None, None, "x10Hours", 1),
            }

            K171 = K121 = K161 = 0
            cc_flags = {}
            respD = await DG.read_discrete_inputs(0x00, 100, slave=slave_id)
            respA = await DG.read_input_registers(0x00, 30, slave=slave_id)
            if not respA.isError():
                for i, reg in enumerate(respA.registers):
                    addr = 0x00 + i
                    val = int(reg)
                    if addr in analog_map:
                        label, threshold, cond, cc_name, unit, ratio = analog_map[addr]
                        scaled_val = val * ratio

                        print(f"{label:<50}: {scaled_val} {unit}")
                        writer.writerow([
                            imo,
                            serial,
                            addr+30001,
                            label,
                            dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                            scaled_val,
                            unit
                        ])

                        # gán cho các biến đặc biệt (dùng raw value trước khi scale)
                        if addr == 0x19: K171 = val
                        if addr == 0x10: K121 = val
                        if addr == 0x18: K161 = val

                        # check alarm (dùng raw val vì threshold đã theo raw)
                        if threshold is not None and cc_name:
                            if cond == ">=":
                                cc_flags[cc_name] = val >= threshold
                            elif cond == "<=":
                                cc_flags[cc_name] = val <= threshold

                # logic phụ
                cc_flags["cc11"] = (K171 > 815 and K121 <= 15)
                cc_flags["cc13"] = (K171 > 815 and K161 <= 35)
            else:
                print(f"❌ Error reading analog registers from {dg_name}")
                flag = True


            # ---------------- DISCRETE ----------------
            print(f"\n✅ {dg_name} Digital Signal")
            discrete_map = {
                0x00: (f"{dg_name} Lub oil filter diff. press - High", "TP6a", True),
                0x08: (f"{dg_name} Lub. oil for turbocharger pressure - Low", "TP2a", True),
                0x0B: (f"{dg_name} Fuel oil leak tank level - High", None, False),
                #0x0C: (f"{dg_name} Lub oil sump tank level - Low", None, False),
                0x10: (f"{dg_name} Engine run", None, False),
                0x11: (f"{dg_name} Ready to start", None, False),
                0x12: (f"{dg_name} Over speed (stop)", None, False),
                0x13: (f"{dg_name} High temp. cooling water outlet temp. (stop) - High", None, False),
                0x14: (f"{dg_name} Lub oil inlet pressure (stop) - Low", None, False),
                0x16: (f"{dg_name} Emergency stop (Remote / Local)", None, False),
                0x17: (f"{dg_name} Start failure", None, False),
                0x18: (f"{dg_name} Priming pump thermal failure", None, False),
                0x19: (f"{dg_name} Priming lub. oil pressure (Low)", "TP4a", True),
                0x1A: (f"{dg_name} Priming pump run", None, True),
                0x20: (f"{dg_name} System failure", None, False),
                0x21: (f"{dg_name} Control module failure", None, False),
                0x22: (f"{dg_name} Safety module failure", None, False),
                0x23: (f"{dg_name} Link to engine condition display failure", None, False),
                0x24: (f"{dg_name} Link to remote I/O-1 failure", None, False),
                0x25: (f"{dg_name} Link To Remote I/O -2 failure", None, False),
                0x3A: (f"{dg_name} Emergency stop switch of external", None, False),
                0x3B: (f"{dg_name} Emergency stop switch on ECD", None, False),
                0x3C: (f"{dg_name} High temp. cooling water temp. switch (High temp)", None, False),
                0x3D: (f"{dg_name} Lub. oil pressure switch (Low press)", None, False),
                0x3F: (f"{dg_name} Emergency stop solenoid valve", None, False),
                0x42: (f"{dg_name} Lub. oil engine inlet temp. sensor failure", None, False),
                0x43: (f"{dg_name} High temp. cooling water engine outlet temp. sensor failure", None, False),
                0x45: (f"{dg_name} No.1 cylinder exhaust gas temp. sensor failure", None, False),
                0x46: (f"{dg_name} No.2 cylinder exhaust gas temp. sensor failure", None, False),
                0x47: (f"{dg_name} No.3 cylinder exhaust gas temp. sensor failure", None, False),
                0x48: (f"{dg_name} No.4 cylinder exhaust gas temp. sensor failure", None, False),
                0x49: (f"{dg_name} No.5 cylinder exhaust gas temp. sensor failure", None, False),
                0x4A: (f"{dg_name} No.6 cylinder exhaust gas temp. sensor failure", None, False),
                0x4D: (f"{dg_name} Exhaust gas T/C inlet 1 temp. sensor failure", None, False),
                0x4E: (f"{dg_name} Exhaust gas T/C inlet 2 temp. sensor failure", None, False),
                0x4F: (f"{dg_name} Exhaust gas T/C outler temp. sensor failure", None, False),
                0x50: (f"{dg_name} High temp. cooling water presure inlet sensor failure", None, False),
                0x52: (f"{dg_name} Low temp. cooling water presure inlet sensor failure", None, False),
                0x53: (f"{dg_name} Starting air presure sensor failure", None, False),
                0x54: (f"{dg_name} Fuel oil engine inlet pressure sensor failure", None, False),
                0x58: (f"{dg_name} Lub oil engine inlet pressure sensor failure", None, False),
                0x59: (f"{dg_name} All speed pickup sensor failure", None, False),
                0x5A: (f"{dg_name} Load input failure", None, False),
            }
            #respD = await DG.read_discrete_inputs(0x00, 92, slave=slave_id)
            if not respD.isError():
                for i, bit_val in enumerate(respD.bits):
                    addr = 0x00 + i
                    if addr in discrete_map:
                        label, tp_key, inv = discrete_map[addr]
                        raw_val = bool(bit_val)

                        # If tp_key & inv=True then reverse the logic according to TP_VALUES
                        val = (raw_val and not TP_VALUES.get(tp_key, False)) if (tp_key and inv) else raw_val

                        print(f"{label:<70}: {val}")
                        writer.writerow([
                            imo,
                            serial,
                            addr + 10001,
                            label,
                            dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                            val,
                            "ON/OFF"
                        ])

                cc_labels = {
                    "cc1":  f"{dg_name} No.1 cylinder exhaust gas temp. (High)",
                    "cc2":  f"{dg_name} No.2 cylinder exhaust gas temp. (High)",
                    "cc3":  f"{dg_name} No.3 cylinder exhaust gas temp. (High)",
                    "cc4":  f"{dg_name} No.4 cylinder exhaust gas temp. (High)",
                    "cc5":  f"{dg_name} No.5 cylinder exhaust gas temp. (High)",
                    "cc6":  f"{dg_name} No.6 cylinder exhaust gas temp. (High)",
                    "cc7":  f"{dg_name} Exhaust gas T/C inlet 1 temp. (High)",
                    "cc8":  f"{dg_name} Exhaust gas T/C inlet 2 temp. (High)",
                    "cc9":  f"{dg_name} Exhaust gas T/C outlet temp. (High)",
                    "cc10": f"{dg_name} High temp. cooling water outlet temp. (High)",
                    "cc11": f"{dg_name} High temp. cooling water inlet press. (Low)",
                    "cc12": f"{dg_name} Low temp. cooling water inlet press. (Low)",
                    "cc13": f"{dg_name} Lub oil engine inlet pressure (Low)",
                    "cc14": f"{dg_name} Lub oil engine inlet temp. (High)",
                    "cc15": f"{dg_name} Fuel oil engine inlet pressure (Low)",
                    "cc16": f"{dg_name} Starting air pressure (Low)",
                    "cc17": f"{dg_name} Over speed (High)",
                }            
                print(f"\n=== ✅ {dg_name} Analog Alarm ===")
                for key, label in cc_labels.items():
                    val = cc_flags.get(key)
                    print(f"{label:<70}: {val}")
                    #writer.writerow([imo, serial, key, label, dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"), val, "ON/OFF"])
            else:
                print(f"❌ Error reading Digital registers from {dg_name}")
                flag = True

            # ---------------- ALARMS ----------------
            

        if flag == False:
            print(f"\n=== ✅ WRITE {dg_name} DATA TO CSV SUCCESSFULLY")

    except Exception as e:
        print(f"❌ Error in read_modbus_data for {dg_name}: {e}")
        traceback.print_exc()
        await asyncio.sleep(0.1)

# ------------------- Client -------------------
async def connect_client(client, address):
    while not client.connected:
        print(f"🔌 Connecting to {address}...")
        await client.connect()
        if client.connected:
            print(f"✅ Connected {address}")
            return
        await asyncio.sleep(0.5)

async def monitor_connection(client, address):
    while True:
        if not client.connected:
            print(f"⚠ Lost {address}, reconnecting...")
            await connect_client(client, address)
        await asyncio.sleep(0.1)


async def connect_client_once(client, address):
    print(f"🔌 Connecting to {address}...")
    await client.connect()
    if client.connected:
        print(f"✅ Connected {address}")
        return True
    print(f"❌ Failed to connect {address}")
    return False

# ------------------- Main -------------------
async def main():
    DG1 = AsyncModbusTcpClient(DG1_IP, timeout=1)
    DG2 = AsyncModbusTcpClient(DG2_IP, timeout=1)
    DG3 = AsyncModbusTcpClient(DG3_IP, timeout=1)
    try:
        while True:
            try:
                if DG1.connected or await connect_client_once(DG1, DG1_IP):
                    try:
                        await read_modbus_data(DG1, DG1_SLAVE_ID, DG1_Name, IMO_NO, DG1_SerialNo)
                    except Exception as e:
                        print(f"Error in read_modbus_data DG#1: {e}")
                        traceback.print_exc()
                        await DG1.close()
                else:
                    print("⚠ Skip DG#1 this cycle.")

                if DG2.connected or await connect_client_once(DG2, DG2_IP):
                    try:
                        await read_modbus_data(DG2, DG2_SLAVE_ID, DG2_Name, IMO_NO, DG2_SerialNo)
                    except Exception as e:
                        print(f"Error in read_modbus_data DG#2: {e}")
                        traceback.print_exc()
                        await DG2.close()
                else:
                    print("⚠ Skip DG#2 this cycle.")

                if DG3.connected or await connect_client_once(DG3, DG3_IP):
                    try:
                        await read_modbus_data(DG3, DG3_SLAVE_ID, DG3_Name, IMO_NO, DG3_SerialNo)
                    except Exception as e:
                        print(f"Error in read_modbus_data DG#3: {e}")
                        traceback.print_exc()
                        await DG3.close()
                else:
                    print("⚠ Skip DG#3 this cycle.")

            except Exception as e:
                print(f"Error in main cycle: {e}")
                traceback.print_exc()

            print("\n=== ✅ WAITING 60s ===")
            await asyncio.sleep(60)

    finally:
        print("🔻 Closing clients...")
        await DG1.close()
        await DG2.close()
        await DG3.close()
        print("✅ All clients closed.")

if __name__ == "__main__":
    asyncio.run(main())
