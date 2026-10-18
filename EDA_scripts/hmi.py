#this Scipt is applied for DB66-02 and DB45-02
import asyncio
import traceback
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusIOException
# ------------------- Configuration -------------------
HMI_IP = "192.168.100.14"
DG1_IP = "192.168.100.11"
DG2_IP = "192.168.100.12"
DG3_IP = "192.168.100.13"
HMI_SLAVE_ID = 0x03
DG1_SLAVE_ID = 16
DG2_SLAVE_ID = 16
DG3_SLAVE_ID = 16
# Global storage
zero_values = [0] * 27
TP_VALUES = {}


def scale_value_for_hmi(addr, val):
    """Convert engine raw values to the unit expected by HMI."""
    if addr == 0x1C:
        return val * 10
    return val


async def mark_dg1_unavailable(HMI):
    """Reflect DG1 communication loss on HMI without blocking the scan loop."""
    await HMI.write_coil(109, True, slave=HMI_SLAVE_ID)
    await HMI.write_registers(0x66, zero_values, slave=HMI_SLAVE_ID)


async def mark_dg2_unavailable(HMI):
    """Reflect DG2 communication loss on HMI without blocking the scan loop."""
    await HMI.write_coil(309, True, slave=HMI_SLAVE_ID)
    await HMI.write_registers(0xCA, zero_values, slave=HMI_SLAVE_ID)


async def mark_dg3_unavailable(HMI):
    """Reflect DG3 communication loss on HMI without blocking the scan loop."""
    await HMI.write_coil(509, True, slave=HMI_SLAVE_ID)
    await HMI.write_registers(0x12E, zero_values, slave=HMI_SLAVE_ID)
# ------------------- Modbus Initialization -------------------
async def initialize_modbus_state(HMI):
    """Reset Modbus states before starting."""
    try:
        # Map: address â†’ description
        coils_to_reset = {
            509: "Serial Link failure DG#3",
            309: "Serial Link failure DG#2",
            109: "Serial Link failure DG#1",
            602: "Restarting",
            601: "Shutting Down",
            600: "In Operation",
            603: "unmounted message",
            604: "mounted message",
        }

        for addr, desc in coils_to_reset.items():
            await HMI.write_coil(addr, False, slave=HMI_SLAVE_ID)
            print(f"ðŸ”„ Reset coil {addr:<50} â†’ {desc}")
            await asyncio.sleep(0.05)  # small delay for CPU to process

        print("âœ… Modbus states initialized.")
    except Exception as e:
        print(f"âš  Error initializing Modbus states: {e}")
        traceback.print_exc()
# ------------------- DG1 Data Reader -------------------
async def read_modbus_data_dg1(DG1, HMI):
    """Read and process Modbus data of DG#1 using mapping tables."""
    try:
        error_check = False
        await HMI.write_coil(600, True, slave=HMI_SLAVE_ID)#Write IN OPERATION
        # --- Repose Inputs (TP1a â†’ TP6a) ---
        response = await DG1.read_discrete_inputs(0x28, 6, slave=DG1_SLAVE_ID)
        print("\nâœ… DG1 Repose Status")
        if not response.isError():
            for i, key in enumerate(["TP1a", "TP2a", "TP3a", "TP4a", "TP5a", "TP6a"]):
                TP_VALUES[key] = response.bits[i]
                print(f"DG1 {key:<50}: {TP_VALUES[key]}")
        await asyncio.sleep(0.05)

        # ========== ANALOG ==========
        print("\nâœ… DG1 Analog Signal")
        analog_map_DG1 = {
            0x02: ("Lub. oil temp. engine inlet", 65, ">=", "cc14", 0x66),
            0x03: ("High temp. cooling water temp. engine outlet", 90, ">=", "cc10", 0x67),
            0x05: ("No.1 cylinder exhaust gas temp.", 480, ">=", "cc1", 0x69),
            0x06: ("No.2 cylinder exhaust gas temp.", 480, ">=", "cc2", 0x6A),
            0x07: ("No.3 cylinder exhaust gas temp.", 480, ">=", "cc3", 0x6B),
            0x08: ("No.4 cylinder exhaust gas temp.", 480, ">=", "cc4", 0x6C),
            0x09: ("No.5 cylinder exhaust gas temp.", 480, ">=", "cc5", 0x6D),
            0x0A: ("No.6 cylinder exhaust gas temp.", 480, ">=", "cc6", 0x6E),
            0x0D: ("Exhaust gas temp. T/C inlet 1", 580, ">=", "cc7", 0x71),
            0x0E: ("Exhaust gas temp. T/C inlet 2", 580, ">=", "cc8", 0x72),
            0x0F: ("Exhaust gas temp. T/C outlet", 480, ">=", "cc9", 0x73),
            0x10: ("High temp. cooling water presure engine inlet", 15, "<=", "cc11", 0x74),
            0x12: ("Low temp. cooling water presure engine inlet", 15, "<=", "cc12", 0x76),
            0x13: ("Starting air pressure", 150, "<=", "cc16", 0x77),
            0x14: ("Fuel oil pressure engine inlet", 35, "<=", "cc15", 0x78),
            0x18: ("Lub. oil pressure", 35, "<=", "cc13", 0x7C),
            0x19: ("Engine speed", 1020, ">=", "cc17", 0x7D),
            0x1B: ("Load", None, None, None, 0x7F),
            0x1C: ("Running hour", None, None, None, 0x80),
        }
        K171 = K121 = K161 = 0
        cc11 = cc13 = False
        resp = await DG1.read_input_registers(0x00, 30, slave=DG1_SLAVE_ID)
        if not resp.isError():
            for i, reg in enumerate(resp.registers):
                addr = 0x00 + i
                val = int(reg)
                if addr in analog_map_DG1:
                    label, threshold, cond, cc_name, hmi_addr = analog_map_DG1[addr]
                    hmi_val = scale_value_for_hmi(addr, val)
                    await HMI.write_register(hmi_addr, hmi_val, slave=HMI_SLAVE_ID)
                    print(f"DG1 {label:<50}: {hmi_val}")
                    if addr == 0x19: K171 = val
                    if addr == 0x10: K121 = val
                    if addr == 0x18: K161 = val
                    if threshold is not None and cc_name:
                        if cond == ">=":
                            locals()[cc_name] = val >= threshold
                        elif cond == "<=":
                            locals()[cc_name] = val <= threshold

            cc11 = (K171 > 815 and K121 <= 15)
            cc13 = (K171 > 815 and K161 <= 35)
        else:
            print("âŒ Error reading analog registers from DG1")
            error_check = True
        # ---------------- Discrete Alarm Mapping ----------------
        print("\nâœ… DG1 Digital Signal")
        # ========== DISCRETE ==========
        discrete_map_DG1 = {
            0x00: ("Lub oil filter diff. press - High", "TP6a", True, 0x00),
            0x08: ("Lub. oil for turbocharger pressure - Low", "TP2a", True, 0x08),
            0x0B: ("Fuel oil leak tank level - High", None, False, 0x0B),
            0x0C: ("LO sump tank level low", None, False, 0x0C),
            0x10: ("Engine run", None, False, 0x10),
            0x11: ("Ready to start", None, False, 0x11),
            0x12: ("Over speed (stop)", None, False, 0x12),
            0x13: ("High temp. cooling water outlet temp. (stop) - High", None, False, 0x13),
            0x14: ("Lub oil inlet pressure (stop) - Low", None, False, 0x14),
            0x16: ("Emergency stop (Remote / Local)", None, False, 0x16),
            0x17: ("Start failure", None, False, 0x17),
            0x18: ("Priming pump thermal failure", None, False, 0x18),
            0x19: ("Priming lub. oil pressure (Low)", "TP4a", True, 0x19),
            0x20: ("System failure", None, False, 0x20),
            0x21: ("Control module failure", None, False, 0x21),
            0x22: ("Safety module failure", None, False, 0x22),
            0x23: ("Link to engine condition display failure", None, False, 0x23),
            0x24: ("Link to remote I/O-1 failure", None, False, 0x24),
            0x25: ("Link to remote I/O-2 failure", None, False, 0x25),
            0x3A: ("Emergency stop switch external", None, False, 0x3A),
            0x3B: ("Emergency stop switch ECD", None, False, 0x3B),
            0x3C: ("High temp. cooling water temp. switch (High temp)", None, False, 0x3C),
            0x3D: ("Lub. oil pressure switch (Low press)", None, False, 0x3D),
            0x3F: ("Emergency stop solenoid valve", None, False, 0x3F),
            0x42: ("Lub. oil engine inlet temp. sensor failure", None, False, 0x42),
            0x43: ("High temp. cooling water engine outlet temp. sensor failure", None, False, 0x43),
            0x45: ("No.1 cylinder exhaust gas temp. sensor failure", None, False, 0x45),
            0x46: ("No.2 cylinder exhaust gas temp. sensor failure", None, False, 0x46),
            0x47: ("No.3 cylinder exhaust gas temp. sensor failure", None, False, 0x47),
            0x48: ("No.4 cylinder exhaust gas temp. sensor failure", None, False, 0x48),
            0x49: ("No.5 cylinder exhaust gas temp. sensor failure", None, False, 0x49),
            0x4A: ("No.6 cylinder exhaust gas temp. sensor failure", None, False, 0x4A),
            0x4D: ("Exhaust gas T/C inlet 1 temp. sensor failure", None, False, 0x4D),
            0x4E: ("Exhaust gas T/C inlet 2 temp. sensor failure", None, False, 0x4E),
            0x4F: ("Exhaust gas T/C outler temp. sensor failure", None, False, 0x4F),
            0x50: ("High temp. cooling water presure inlet sensor failure", None, False, 0x50),
            0x52: ("Low temp. cooling water presure inlet sensor failure", None, False, 0x52),
            0x53: ("Starting air presure sensor failure", None, False, 0x53),
            0x54: ("Fuel oil engine inlet pressure sensor failure", None, False, 0x54),
            0x58: ("Lub oil engine inlet pressure sensor failure", None, False, 0x58),
            0x59: ("All speed pickup sensor failure", None, False, 0x59),
            0x5A: ("Load input failure", None, False, 0x5A),
            
        }

        Z_flags = {}
        resp = await DG1.read_discrete_inputs(0x00, 92, slave=DG1_SLAVE_ID)
        if not resp.isError():
            for dg_addr, (label, tp_key, inv, hmi_addr) in discrete_map_DG1.items():
                bit_index = dg_addr - 0x00   # dá»‹ch Ä‘á»‹a chá»‰ vá» index trong resp.bits
                if 0 <= bit_index < len(resp.bits):
                    raw_val = resp.bits[bit_index]
                    val = raw_val and not TP_VALUES.get(tp_key, False) if tp_key and inv else raw_val

                    # Print status: Engine Run/Ready
                    print(f"DG1 {label:<50}: {val}")

                    # Z_flags If it's not Engine Run/Ready
                    if dg_addr not in (0x10, 0x11):
                        Z_flags[dg_addr] = val

                    await HMI.write_coil(hmi_addr, val, slave=HMI_SLAVE_ID)
        else:
            print("âŒ Error reading discrete inputs from DG1")
            error_check = True

        # ========== Tá»•ng há»£p Alarm ==========
        # Collect all alarm bits cc1â€“cc17 into a list
        alarm_bits = [
            locals().get("cc1"), locals().get("cc2"), locals().get("cc3"),
            locals().get("cc4"), locals().get("cc5"), locals().get("if addr in discrete_map_DG1cc6"),
            locals().get("cc7"), locals().get("cc8"), locals().get("cc9"),
            locals().get("cc10"), cc11, locals().get("cc12"),
            cc13, locals().get("cc14"), locals().get("cc15"),
            locals().get("cc16"), locals().get("cc17")
        ]

        # cc18 = alarm LED (active if ANY alarm is true or any Z_flags set)

        cc18 = any(alarm_bits) or any(Z_flags.values())

        # Append cc18 to the list for HMI write
        alarm_bits.append(cc18)

        # Write 18 alarm status bits at once to HMI starting from coil 0x5C
        await HMI.write_coils(0x5B, alarm_bits, slave=HMI_SLAVE_ID)

        await HMI.write_coil(600, False, slave=HMI_SLAVE_ID) # OFF OPERATION
        cc_labels = {
            "cc1":  "No 1 Cyl ex temp. (High)",
            "cc2":  "No 2 Cyl ex temp. (High)",
            "cc3":  "No 3 Cyl ex temp. (High)",
            "cc4":  "No 4 Cyl ex temp. (High)",
            "cc5":  "No 5 Cyl ex temp. (High)",
            "cc6":  "No 6 Cyl ex temp. (High)",
            "cc7":  "Ex temp T/C inlet1 (High)",
            "cc8":  "Ex temp T/C inlet2 (High)",
            "cc9":  "Ex temp T/C outlet (High)",
            "cc10": "HT.CW outlet temp (High)",
            "cc11": "HT.CW inlet pressure (Low)",
            "cc12": "LT.CW inlet press (Low)",
            "cc13": "LO. Inlet press (Low)",
            "cc14": "LO. Inlet temp (High)",
            "cc15": "FO inlet press (Low)",
            "cc16": "Starting air pressure (Low)",
            "cc17": "Over speed (High)",
            "cc18": "Alarm LED"
        }
        print("\n=== âœ…DG1 Analog Alarm ===")
        for key, label in cc_labels.items():
            val = globals().get(key) or locals().get(key)
            #print(f"DG1 {label:<50} : {val}")

        if error_check == False:
            await HMI.write_coil(109, False, slave=HMI_SLAVE_ID) #Write SERIAL LINK FAIL 
        else: 
            await HMI.write_coil(109, True, slave=HMI_SLAVE_ID) #Write SERIAL LINK FAIL
            await HMI.write_registers(0x66,zero_values, slave=HMI_SLAVE_ID)
    except Exception as e:
        print(f"âŒ Error in read_modbus_data_dg1: {e}")
        await HMI.write_coil(109, True, slave=HMI_SLAVE_ID) #Write SERIAL LINK FAIL
        traceback.print_exc()
        await asyncio.sleep(0.1)
# ------------------- DG2 Data Reader -------------------            
async def read_modbus_data_dg2(DG2, HMI):
    
    """Read and process Modbus data of DG#2 using mapping tables."""
    try:
        error_check = False
        await HMI.write_coil(600, True, slave=HMI_SLAVE_ID)  # Write IN OPERATION
        # --- Repose Inputs (TP1a â†’ TP6a) ---
        response = await DG2.read_discrete_inputs(0x28, 6, slave=DG2_SLAVE_ID)
        print("\nâœ… DG2 Repose Status")
        if not response.isError():
            for i, key in enumerate(["TP1a", "TP2a", "TP3a", "TP4a", "TP5a", "TP6a"]):
                TP_VALUES[key] = response.bits[i]
                print(f"DG2 {key:<50}: {TP_VALUES[key]}")
        await asyncio.sleep(0.05)

        # ========== ANALOG ==========
        print("\nâœ… DG2 Analog Signal")
        analog_map_DG2 = {
            0x02: ("LO Temp engine inlet", 65, ">=", "bb14", 0xCA),
            0x03: ("HT CW Temp engine outlet", 90, ">=", "bb10", 0xCB),
            0x05: ("No1 cyl exhaust temp", 480, ">=", "bb1", 0xCD),
            0x06: ("No2 cyl exhaust temp", 480, ">=", "bb2", 0xCE),
            0x07: ("No3 cyl exhaust temp", 480, ">=", "bb3", 0xCF),
            0x08: ("No4 cyl exhaust temp", 480, ">=", "bb4", 0xD0),
            0x09: ("No5 cyl exhaust temp", 480, ">=", "bb5", 0xD1),
            0x0A: ("No6 cyl exhaust temp", 480, ">=", "bb6", 0xD2),
            0x0D: ("Exh gas T/C inlet1", 580, ">=", "bb7", 0xD5),
            0x0E: ("Exh gas T/C inlet2", 580, ">=", "bb8", 0xD6),
            0x0F: ("Exh gas T/C outlet", 480, ">=", "bb9", 0xD7),
            0x10: ("HT.CW Pressure inlet", 15, "<=", "bb11", 0xD8),
            0x12: ("LT.CW Pressure inlet", 15, "<=", "bb12", 0xDA),
            0x13: ("Starting Air Pressure", 150, "<=", "bb16", 0xDB),
            0x14: ("FO Pressure inlet", 35, "<=", "bb15", 0xDC),
            0x18: ("LO Pressure", 35, "<=", "bb13", 0xE0),
            0x19: ("Engine Speed", 1020, ">=", "bb17", 0xE1),
            0x1B: ("Load", None, None, None, 0xE3),
            0x1C: ("Running hour", None, None, None, 0xE4),
        }
        K171 = K121 = K161 = 0
        bb11 = bb13 = False
        resp = await DG2.read_input_registers(0x00, 30, slave=DG2_SLAVE_ID)
        if not resp.isError():
            for i, reg in enumerate(resp.registers):
                addr = 0x00 + i
                val = int(reg)
                if addr in analog_map_DG2:
                    label, threshold, cond, bb_name, hmi_addr = analog_map_DG2[addr]
                    hmi_val = scale_value_for_hmi(addr, val)
                    await HMI.write_register(hmi_addr, hmi_val, slave=HMI_SLAVE_ID)
                    print(f"DG2 {label:<50}: {hmi_val}")
                    if addr == 0x19: K171 = val
                    if addr == 0x10: K121 = val
                    if addr == 0x18: K161 = val
                    if threshold is not None and bb_name:
                        if cond == ">=":
                            locals()[bb_name] = val >= threshold
                        elif cond == "<=":
                            locals()[bb_name] = val <= threshold

            bb11 = (K171 > 815 and K121 <= 15)
            bb13 = (K171 > 815 and K161 <= 35)
        else:
            print("âŒ Error reading analog registers from DG2")
            error_check = True
        # ---------------- Discrete Alarm Mapping ----------------
        print("\nâœ… DG2 Digital Signal")
        # ========== DISCRETE ==========
        discrete_map_DG2 = {
            0x00: ("LO Filter Diff Pressure", "TP6a", True, 0xC8),
            0x08: ("LO for T/C Pressure", "TP2a", True, 0xD0),
            0x0B: ("FO Leak Tank Level", None, False, 0xD3),
            0x10: ("Engine Run", None, False, 0xD8),
            0x11: ("Engine Ready", None, False, 0xD9),
            0x12: ("Over speed", None, False, 0xDA),
            0x13: ("HT.CW outlet temp", None, False, 0xDB),
            0x14: ("LO inlet pressure(stop)", None, False, 0xDC),
            0x16: ("Emergency stop(Remote/Local)", None, False, 0xDE),
            0x17: ("Start failure", None, False, 0xDF),
            0x18: ("Priming pump thermal failure", None, False, 0xE0),
            0x19: ("Priming pump LO pressure(Low)", "TP4a", True, 0xE1),
            0x20: ("System failure", None, False, 0xE8),
            0x21: ("Control module failure", None, False, 0xE9),
            0x22: ("Safety module failure", None, False, 0xEA),
            0x23: ("Link to engine condition display failure", None, False, 0xEB),
            0x24: ("Link to remote I/O-1 failure", None, False, 0xEC),
            0x25: ("Link to remote I/O-2 failure", None, False, 0xED),
            0x3A: ("Emergency stop switch external", None, False, 0x102),
            0x3B: ("Emergency stop switch ECD", None, False, 0x103),
            0x3C: ("HT.CW temp high", None, False, 0x104),
            0x3D: ("LO pressure low", None, False, 0x105),
            0x3F: ("Emergency solenoid valve", None, False, 0x107),
            0x42: ("LO engine inlet temp sensor", None, False, 0x10A),
            0x43: ("HT.CW engine outlet temp sensor failure", None, False, 0x10B),
            0x45: ("No.1 cyl exhaust temp sensor fail", None, False, 0x10D),
            0x46: ("No.2 cyl exhaust temp sensor fail", None, False, 0x10E),
            0x47: ("No.3 cyl exhaust temp sensor fail", None, False, 0x10F),
            0x48: ("No.4 cyl exhaust temp sensor fail", None, False, 0x110),
            0x49: ("No.5 cyl exhaust temp sensor fail", None, False, 0x111),
            0x4A: ("No.6 cyl exhaust temp sensor fail", None, False, 0x112),
            0x4D: ("Exh gas T/C inlet1 sensor fail", None, False, 0x115),
            0x4E: ("Exh gas T/C inlet2 sensor fail", None, False, 0x116),
            0x4F: ("Exh gas T/C outlet sensor fail", None, False, 0x117),
            0x50: ("HT.CW pressure inlet sensor fail", None, False, 0x118),
            0x52: ("LT.CW pressure inlet sensor fail", None, False, 0x11A),
            0x53: ("Starting air pressure sensor fail", None, False, 0x11B),
            0x54: ("FO engine inlet pressure sensor fail", None, False, 0x11C),
            0x58: ("LO engine inlet pressure sensor fail", None, False, 0x120),
            0x59: ("All speed pickup sensor fail", None, False, 0x121),
            0x5A: ("Load input failure", None, False, 0x122)
        }         

        Z_flags = {}
        resp = await DG2.read_discrete_inputs(0x00, 92, slave=DG2_SLAVE_ID)
        if not resp.isError():
            for dg_addr, (label, tp_key, inv, hmi_addr) in discrete_map_DG2.items():
                bit_index = dg_addr - 0x00   # dá»‹ch Ä‘á»‹a chá»‰ vá» index trong resp.bits
                if 0 <= bit_index < len(resp.bits):
                    raw_val = resp.bits[bit_index]
                    val = raw_val and not TP_VALUES.get(tp_key, False) if tp_key and inv else raw_val

                    # Print status: Engine Run/Ready
                    print(f"DG2 {label:<50}: {val}")

                    # Chá»‰ Ä‘Æ°a vÃ o Z_flags náº¿u khÃ´ng pháº£i Engine Run/Ready
                    if dg_addr not in (0x10, 0x11):
                        Z_flags[dg_addr] = val

                    await HMI.write_coil(hmi_addr, val, slave=HMI_SLAVE_ID)
        else:
            print("âŒ Error reading discrete inputs from DG2")
            error_check = True

        # ========== Tá»•ng há»£p Alarm ==========
        # Collect all alarm bits bb1â€“bb17 into a list
        alarm_bits = [
            locals().get("bb1"), locals().get("bb2"), locals().get("bb3"),
            locals().get("bb4"), locals().get("bb5"), locals().get("bb6"),
            locals().get("bb7"), locals().get("bb8"), locals().get("bb9"),
            locals().get("bb10"), bb11, locals().get("bb12"),
            bb13, locals().get("bb14"), locals().get("bb15"),
            locals().get("bb16"), locals().get("bb17")
        ]

        # bb18 = alarm LED (active if ANY alarm is true or any Z_flags set)
        bb18 = any(alarm_bits) or any(Z_flags.values())

        # Append bb18 to the list for HMI write
        alarm_bits.append(bb18)

        # Write 18 alarm status bits at once to HMI starting from coil 0x5C
        await HMI.write_coils(0x123, alarm_bits, slave=HMI_SLAVE_ID)

        await HMI.write_coil(600, False, slave=HMI_SLAVE_ID)  # OFF OPERATION
        bb_labels = {
            "bb1":  "No 1 Cyl ex temp. (High)",
            "bb2":  "No 2 Cyl ex temp. (High)",
            "bb3":  "No 3 Cyl ex temp. (High)",
            "bb4":  "No 4 Cyl ex temp. (High)",
            "bb5":  "No 5 Cyl ex temp. (High)",
            "bb6":  "No 6 Cyl ex temp. (High)",
            "bb7":  "Ex temp T/C inlet1 (High)",
            "bb8":  "Ex temp T/C inlet2 (High)",
            "bb9":  "Ex temp T/C outlet (High)",
            "bb10": "HT.CW outlet temp (High)",
            "bb11": "HT.CW inlet pressure (Low)",
            "bb12": "LT.CW inlet press (Low)",
            "bb13": "LO. Inlet press (Low)", ## can kiem tra lai, LO tat may => ko bao alarm)
            "bb14": "LO. Inlet temp (High)",
            "bb15": "FO inlet press (Low)",
            "bb16": "Starting air pressure (Low)",
            "bb17": "Over speed (High)",
            "bb18": "Alarm LED"
        }
        print("\n=== âœ…DG2 Analog Alarm ===")
        for key, label in bb_labels.items():
            val = globals().get(key) or locals().get(key)
            #print(f"DG2 {label:<50} : {val}")
            
        if error_check == False:
            await HMI.write_coil(309, False, slave=HMI_SLAVE_ID) #Write SERIAL LINK FAIL 
        else:
            await HMI.write_coil(309, True, slave=HMI_SLAVE_ID) #Write SERIAL LINK FAIL
            await HMI.write_registers(0xCA,zero_values, slave=HMI_SLAVE_ID)
    except Exception as e:
        print(f"âŒ Error in read_modbus_data_dg2: {e}")
        await HMI.write_coil(309, True, slave=HMI_SLAVE_ID)  # Write SERIAL LINK FAIL
        traceback.print_exc()
        await asyncio.sleep(0.1)
# ------------------- DG3 Data Reader -------------------
async def read_modbus_data_dg3(DG3, HMI):
    
    """Read and process Modbus data of DG#3 using mapping tables."""
    try:
        error_check = False
        await HMI.write_coil(600, True, slave=HMI_SLAVE_ID)  # Write IN OPERATION
        # --- Repose Inputs (TP1a â†’ TP6a) ---
        response = await DG3.read_discrete_inputs(0x28, 6, slave=DG3_SLAVE_ID)
        print("\nâœ… DG3 Repose Status")
        if not response.isError():
            for i, key in enumerate(["TP1a", "TP2a", "TP3a", "TP4a", "TP5a", "TP6a"]):
                TP_VALUES[key] = response.bits[i]
                print(f"DG3 {key:<50}: {TP_VALUES[key]}")
        await asyncio.sleep(0.05)

        # ========== ANALOG ==========
        print("\nâœ… DG3 Analog Signal")
        analog_map_DG3 = {
            0x02: ("LO Temp engine inlet", 65, ">=", "aa14", 0x12E),
            0x03: ("HT CW Temp engine outlet", 90, ">=", "aa10", 0x12F),
            0x05: ("No1 cyl exhaust temp", 480, ">=", "aa1", 0x131),
            0x06: ("No2 cyl exhaust temp", 480, ">=", "aa2", 0x132),
            0x07: ("No3 cyl exhaust temp", 480, ">=", "aa3", 0x133),
            0x08: ("No4 cyl exhaust temp", 480, ">=", "aa4", 0x134),
            0x09: ("No5 cyl exhaust temp", 480, ">=", "aa5", 0x135),
            0x0A: ("No6 cyl exhaust temp", 480, ">=", "aa6", 0x136),
            0x0D: ("Exh gas T/C inlet1", 580, ">=", "aa7", 0x139),
            0x0E: ("Exh gas T/C inlet2", 580, ">=", "aa8", 0x13A),
            0x0F: ("Exh gas T/C outlet", 480, ">=", "aa9", 0x13B),
            0x10: ("HT.CW Pressure inlet", 15, "<=", "aa11", 0x13C),
            0x12: ("LT.CW Pressure inlet", 15, "<=", "aa12", 0x13E),
            0x13: ("Starting Air Pressure", 150, "<=", "aa16", 0x13F),
            0x14: ("FO Pressure inlet", 35, "<=", "aa15", 0x140),
            0x18: ("LO Pressure", 35, "<=", "aa13", 0x144),
            0x19: ("Engine Speed", 1020, ">=", "aa17", 0x145),
            0x1B: ("Load", None, None, None, 0x147),
            0x1C: ("Running hour", None, None, None, 0x148),
        }
        X171 = X121 = X161 = 0
        aa11 = aa13 = False
        resp = await DG3.read_input_registers(0x00, 30, slave=DG3_SLAVE_ID)
        if not resp.isError():
            for i, reg in enumerate(resp.registers):
                addr = 0x00 + i
                val = int(reg)
                if addr in analog_map_DG3:
                    label, threshold, cond, aa_name, hmi_addr = analog_map_DG3[addr]
                    hmi_val = scale_value_for_hmi(addr, val)
                    await HMI.write_register(hmi_addr, hmi_val, slave=HMI_SLAVE_ID)
                    print(f"DG3 {label:<50}: {hmi_val}")
                    if addr == 0x19: X171 = val
                    if addr == 0x10: X121 = val
                    if addr == 0x18: X161 = val
                    if threshold is not None and aa_name:
                        if cond == ">=":
                            locals()[aa_name] = val >= threshold
                        elif cond == "<=":
                            locals()[aa_name] = val <= threshold

            aa11 = (X171 > 815 and X121 <= 15)
            aa13 = (X171 > 815 and X161 <= 35)
        else:
            print("âŒ Error reading analog registers from DG3")
            error_check = True
        # ---------------- Discrete Alarm Mapping ----------------
        print("\nâœ… DG3 Digital Signal")
        discrete_map_DG3 = {
            0x00: ("LO Filter Diff Pressure", "TP6a", True, 0x190),
            0x08: ("LO for T/C Pressure", "TP2a", True, 0x198),
            0x0B: ("FO Leak Tank Level", None, False, 0x19B),
            0x0C: ("LO sump tank level low", None, False, 0x19C),
            0x10: ("Engine Run", None, False, 0x1A0),
            0x11: ("Engine Ready", None, False, 0x1A1),
            0x12: ("Over speed", None, False, 0x1A2),
            0x13: ("HT.CW outlet temp", None, False, 0x1A3),
            0x14: ("LO inlet pressure(stop)", None, False, 0x1A4),
            0x16: ("Emergency stop(Remote/Local)", None, False, 0x1A6),
            0x17: ("Start failure", None, False, 0x1A7),
            0x18: ("Priming pump thermal failure", None, False, 0x1A8),
            0x19: ("Priming pump LO pressure(Low)", "TP4a", True, 0x1A9),
            0x20: ("System failure", None, False, 0x1B0),
            0x21: ("Control module failure", None, False, 0x1B1),
            0x22: ("Safety module failure", None, False, 0x1B2),
            0x23: ("Link to engine condition display failure", None, False, 0x1B3),
            0x24: ("Link to remote I/O-1 failure", None, False, 0x1B4),
            0x25: ("Link to remote I/O-2 failure", None, False, 0x1B5),
            0x3A: ("Emergency stop switch external", None, False, 0x1CA),
            0x3B: ("Emergency stop switch ECD", None, False, 0x1CB),
            0x3C: ("HT.CW temp high", None, False, 0x1CC),
            0x3D: ("LO pressure low", None, False, 0x1CD),
            0x3F: ("Emergency solenoid valve", None, False, 0x1CF),
            0x42: ("LO engine inlet temp sensor", None, False, 0x1D2),
            0x43: ("HT.CW engine outlet temp sensor failure", None, False, 0x1D3),
            0x45: ("No.1 cyl exhaust temp sensor fail", None, False, 0x1D5),
            0x46: ("No.2 cyl exhaust temp sensor fail", None, False, 0x1D6),
            0x47: ("No.3 cyl exhaust temp sensor fail", None, False, 0x1D7),
            0x48: ("No.4 cyl exhaust temp sensor fail", None, False, 0x1D8),
            0x49: ("No.5 cyl exhaust temp sensor fail", None, False, 0x1D9),
            0x4A: ("No.6 cyl exhaust temp sensor fail", None, False, 0x1DA),
            0x4D: ("Exh gas T/C inlet1 sensor fail", None, False, 0x1DD),
            0x4E: ("Exh gas T/C inlet2 sensor fail", None, False, 0x1DE),
            0x4F: ("Exh gas T/C outlet sensor fail", None, False, 0x1DF),
            0x50: ("HT.CW pressure inlet sensor fail", None, False, 0x1E0),
            0x52: ("LT.CW pressure inlet sensor fail", None, False, 0x1E2),
            0x53: ("Starting air pressure sensor fail", None, False, 0x1E3),
            0x54: ("FO engine inlet pressure sensor fail", None, False, 0x1E4),
            0x58: ("LO engine inlet pressure sensor fail", None, False, 0x1E8),
            0x59: ("All speed pickup sensor fail", None, False, 0x1E9),
            0x5A: ("Load input failure", None, False, 0x1EA),
        }

        Z_flags = {}
        resp = await DG3.read_discrete_inputs(0x00, 92, slave=DG3_SLAVE_ID)
        if not resp.isError():
            for dg_addr, (label, tp_key, inv, hmi_addr) in discrete_map_DG3.items():
                bit_index = dg_addr - 0x00
                if 0 <= bit_index < len(resp.bits):
                    raw_val = resp.bits[bit_index]
                    val = raw_val and not TP_VALUES.get(tp_key, False) if tp_key and inv else raw_val

                    print(f"DG3 {label:<50}: {val}")

                    if dg_addr not in (0x10, 0x11):
                        Z_flags[dg_addr] = val

                    await HMI.write_coil(hmi_addr, val, slave=HMI_SLAVE_ID)
        else:
            print("âŒ Error reading discrete inputs from DG3")
            error_check = True
        # ========== Tá»•ng há»£p Alarm ==========
        alarm_bits = [
            locals().get("aa1"), locals().get("aa2"), locals().get("aa3"),
            locals().get("aa4"), locals().get("aa5"), locals().get("aa6"),
            locals().get("aa7"), locals().get("aa8"), locals().get("aa9"),
            locals().get("aa10"), aa11, locals().get("aa12"),
            aa13, locals().get("aa14"), locals().get("aa15"),
            locals().get("aa16"), locals().get("aa17")
        ]

        aa18 = any(alarm_bits) or any(Z_flags.values())
        alarm_bits.append(aa18)

        await HMI.write_coils(0x1EB, alarm_bits, slave=HMI_SLAVE_ID)

        await HMI.write_coil(600, False, slave=HMI_SLAVE_ID)  # OFF OPERATION
        aa_labels = {
            "aa1":  "No 1 Cyl ex temp. (High)",
            "aa2":  "No 2 Cyl ex temp. (High)",
            "aa3":  "No 3 Cyl ex temp. (High)",
            "aa4":  "No 4 Cyl ex temp. (High)",
            "aa5":  "No 5 Cyl ex temp. (High)",
            "aa6":  "No 6 Cyl ex temp. (High)",
            "aa7":  "Ex temp T/C inlet1 (High)",
            "aa8":  "Ex temp T/C inlet2 (High)",
            "aa9":  "Ex temp T/C outlet (High)",
            "aa10": "HT.CW outlet temp (High)",
            "aa11": "HT.CW inlet pressure (Low)",
            "aa12": "LT.CW inlet press (Low)",
            "aa13": "LO. Inlet press (Low)",
            "aa14": "LO. Inlet temp (High)",
            "aa15": "FO inlet press (Low)",
            "aa16": "Starting air pressure (Low)",
            "aa17": "Over speed (High)",
            "aa18": "Alarm LED"
        }
        print("\n=== âœ…DG3 Analog Alarm ===")
        for key, label in aa_labels.items():
            val = globals().get(key) or locals().get(key)
            #print(f"DG3 {label:<50} : {val}")

        if error_check == False:
            await HMI.write_coil(509, False, slave=HMI_SLAVE_ID) #Write SERIAL LINK FAIL 
        else: 
            await HMI.write_coil(509, True, slave=HMI_SLAVE_ID) #Write SERIAL LINK FAIL
            await HMI.write_registers(0x12E,zero_values, slave=HMI_SLAVE_ID)
    except Exception as e:
        print(f"âŒ Error in read_modbus_data_dg3: {e}")
        await HMI.write_coil(509, True, slave=HMI_SLAVE_ID)  # Write SERIAL LINK FAIL
        traceback.print_exc()
        await asyncio.sleep(0.1)

# ------------------- Client & Connection -------------------
async def connect_client(client, address):
    """Connect to Modbus client."""
    while not client.connected:
        print(f"Ã°Å¸â€Å’ Connecting to {address}...")
        await client.connect()
        if client.connected:
            print(f"Ã¢Å“â€¦ Connected {address}")
            return
        await asyncio.sleep(0.5)


async def connect_client_once(client, address):
    """Try a single Modbus connection attempt without retrying."""
    print(f"Ã°Å¸â€Å’ Connecting to {address}...")
    await client.connect()
    if client.connected:
        print(f"Ã¢Å“â€¦ Connected {address}")
        return True
    print(f"Ã¢ÂÅ’ Failed to connect {address}")
    return False


async def monitor_connection(client, address):
    """Reconnect if client disconnected."""
    while True:
        if not client.connected:
            print(f"Ã¢Å¡Â  Lost {address}, reconnecting...")
            await connect_client(client, address)
        await asyncio.sleep(0.1)
# ------------------- Modbus Reader Loop -------------------
async def modbus_reader(DG, HMI):
    while True:
        try:
            await read_modbus_data_dg1(DG, HMI)
        except Exception as e:
            print(f"Error in modbus_reader DG#1: {e}")
            traceback.print_exc()
        await asyncio.sleep(1)
# ------------------- Main -------------------
async def main():
    """Main loop."""
    initialized = False
    dg1_enabled = True
    dg2_enabled = True
    dg3_enabled = True
    while True:
        HMI = DG1 = DG2 = DG3 = None
        try:
            HMI = AsyncModbusTcpClient(HMI_IP, timeout=5)
            DG1 = AsyncModbusTcpClient(DG1_IP, timeout=1)
            DG2 = AsyncModbusTcpClient(DG2_IP, timeout=1)
            DG3 = AsyncModbusTcpClient(DG3_IP, timeout=1)

            await connect_client(HMI, HMI_IP)

            dg1_enabled = await connect_client_once(DG1, DG1_IP)
            dg2_enabled = await connect_client_once(DG2, DG2_IP)
            dg3_enabled = await connect_client_once(DG3, DG3_IP)

            asyncio.create_task(monitor_connection(HMI, HMI_IP))

            if not initialized:
                await initialize_modbus_state(HMI)
                initialized = True
                print("Ã¢Å“â€¦ Modbus state initialized once.")

            if not dg1_enabled:
                await mark_dg1_unavailable(HMI)
                print("Ã¢Å¡Â  DG1 unavailable. Skipping reconnect attempts to reduce HMI latency.")
            if not dg2_enabled:
                await mark_dg2_unavailable(HMI)
                print("Ã¢Å¡Â  DG2 unavailable. Skipping reconnect attempts to reduce HMI latency.")
            if not dg3_enabled:
                await mark_dg3_unavailable(HMI)
                print("Ã¢Å¡Â  DG3 unavailable. Skipping reconnect attempts to reduce HMI latency.")

            while True:
                if dg1_enabled and DG1.connected:
                    try:
                        await read_modbus_data_dg1(DG1, HMI)
                    except Exception as e:
                        print(f"Error in modbus_reader DG#1: {e}")
                        traceback.print_exc()
                        dg1_enabled = False
                        await DG1.close()
                        await mark_dg1_unavailable(HMI)
                        print("DG1 disabled after read failure. Reconnect attempts remain off.")
                else:
                    await mark_dg1_unavailable(HMI)

                if dg2_enabled and DG2.connected:
                    try:
                        await read_modbus_data_dg2(DG2, HMI)
                    except Exception as e:
                        print(f"Error in modbus_reader DG#2: {e}")
                        traceback.print_exc()
                        dg2_enabled = False
                        await DG2.close()
                        await mark_dg2_unavailable(HMI)
                        print("DG2 disabled after read failure. Reconnect attempts remain off.")
                else:
                    await mark_dg2_unavailable(HMI)

                if dg3_enabled and DG3.connected:
                    try:
                        await read_modbus_data_dg3(DG3, HMI)
                    except Exception as e:
                        print(f"Error in modbus_reader DG#3: {e}")
                        traceback.print_exc()
                        dg3_enabled = False
                        await DG3.close()
                        await mark_dg3_unavailable(HMI)
                        print("DG3 disabled after read failure. Reconnect attempts remain off.")
                else:
                    await mark_dg3_unavailable(HMI)

                await asyncio.sleep(0.5)

        except Exception as e:
            print(f"Error main: {e}")
            traceback.print_exc()
        finally:
            print("Closing clients...")
            clients_to_close = [client.close() for client in (HMI, DG1, DG2, DG3) if client is not None]
            if clients_to_close:
                await asyncio.gather(*clients_to_close)
            print("Clients closed. Restarting...")
if __name__ == "__main__":
    asyncio.run(main())
