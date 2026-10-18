#!/usr/bin/python3
# -*- coding: utf-8 -*-
'''
IMPROVED VERSION v2.0 - Eliminates null values and optimizes performance
pymodbus3.7.2 / python3.9.2
Modbus - Multiple register / discrete inputs query
For the Project: Emarat 64K BC - Dalian Shipyard NDY1274 
Date: 15.Sept.2025
By: Romel Mendoza
Rev 2.0 - Refactored with synchronized data collection and error handling
Key Improvements:
- Eliminates race conditions causing null values
- Optimized connection handling (1 connection/minute vs 600/minute)
- Thread-safe data operations
- Comprehensive error handling and recovery
- Default value protection for all variables
- Maintains exact CSV format compatibility
- Offset address Channel 1 - 0x01 not 0x00
'''

import pymodbus
import datetime
import threading
import schedule
import logging
import time
from time import sleep, strftime
from pymodbus.client import ModbusTcpClient as ModbusClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder, BinaryPayloadBuilder
from collections import OrderedDict
import os
import subprocess
import shutil
import random

print(f"Pymodbus Version: {pymodbus.__version__}")
print("Starting Improved Data Collector v2.0...")

class EnhancedDataCollector:
    """
    Enhanced data collector with synchronized operations and null value prevention
    """
    
    def __init__(self):
        # Connection settings
        self.modbus_host = '192.168.188.235'
        self.modbus_port = 503
        self.modbus_timeout = 5
        self.slave_id = 0x02
        
        # Updated vessel configuration
        self.imo_no = 1043671  # Updated IMO number 
        self.dg1_serial = "DE618Z5246"  # Updated DG1 SerialNo
        self.dg2_serial = "DE618Z5247"  # Updated DG2 SerialNo
        self.dg3_serial = "DE618Z5248"  # Updated DG3 SerialNo
        
        # Thread safety
        self.data_lock = threading.Lock()
        self.collection_in_progress = False
        
        # Data storage for each DG
        self.dg1_data = {}
        self.dg2_data = {}
        self.dg3_data = {}
        
        # Repose signal states
        self.dg1_repose = {}
        self.dg2_repose = {}
        self.dg3_repose = {}
        
        # Statistics
        self.collection_count = 0
        self.error_count = 0
        self.last_collection_time = None
        
        # Setup logging first
        self.setup_logging()
        
        # Initialize all data structures
        self.initialize_data_structures()
        
    def setup_logging(self):
        """Setup logging for debugging and monitoring"""
        try:
            # Ensure the csv_test directory exists
            os.makedirs('/home/drums/csv', exist_ok=True)
            
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler('/home/drums/csv/modbus_collector.log'),
                    logging.StreamHandler()
                ]
            )
            self.logger = logging.getLogger(__name__)
            
        except Exception as e:
            # Fallback to console-only logging if file logging fails
            print(f"Warning: Could not setup file logging: {e}")
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler()]
            )
            self.logger = logging.getLogger(__name__)
            self.logger.warning(f"File logging disabled due to error: {e}")
        
    def initialize_data_structures(self):
        """Initialize all data structures with default values to prevent undefined variables"""
        
        # DG1 Data Initialization
        # Analog data (L1-L19)
        analog_defaults = {
            'L1': 0, 'L2': 0, 'L3': 0, 'L4': 0, 'L5': 0, 'L6': 0, 'L7': 0, 'L8': 0, 'L9': 0,
            'L10': 0, 'L11': 0, 'L12': 0.0, 'L13': 0.0, 'L14': 0.0, 'L15': 0.0, 'L16': 0.0,
            'L17': 0, 'L18': 0, 'L19': 0
        }
        self.dg1_data.update(analog_defaults)
        
        # Digital data (C1-C45)
        for i in range(1, 46):
            self.dg1_data[f'C{i}'] = 0
            
        # DG2 Data Initialization
        # Analog data (K1-K19)
        analog_defaults_k = {f'K{i}': (0.0 if i in [12, 13, 14, 15, 16] else 0) for i in range(1, 20)}
        self.dg2_data.update(analog_defaults_k)
        
        # Digital data (B1-B45)
        for i in range(1, 46):
            self.dg2_data[f'B{i}'] = 0
            
        # DG3 Data Initialization
        # Analog data (J1-J19)
        analog_defaults_j = {f'J{i}': (0.0 if i in [12, 13, 14, 15, 16] else 0) for i in range(1, 20)}
        self.dg3_data.update(analog_defaults_j)
        
        # Digital data (A1-A45)
        for i in range(1, 46):
            self.dg3_data[f'A{i}'] = 0
            
        # Repose signals initialization
        for i in range(1, 6):
            self.dg1_repose[f'RP{i}'] = False
            self.dg2_repose[f'SP{i}'] = False
            self.dg3_repose[f'TP{i}'] = False
            
        if hasattr(self, 'logger'):
            self.logger.info("Data structures initialized with default values")
        else:
            print("Data structures initialized with default values")

    def create_modbus_connection(self):
        """Create and test Modbus connection with proper error handling"""
        try:
            client = ModbusClient(
                host=self.modbus_host,
                port=self.modbus_port,
                timeout=self.modbus_timeout
            )
            
            if client.connect():
                self.logger.debug("Modbus connection established successfully")
                return client
            else:
                self.logger.error("Failed to establish Modbus connection")
                return None
                
        except Exception as e:
            self.logger.error(f"Exception creating Modbus connection: {e}")
            return None

    def read_with_retry(self, client, read_func, *args, max_retries=3):
        """Read Modbus data with retry mechanism"""
        for attempt in range(max_retries):
            try:
                response = read_func(*args, slave=self.slave_id)
                if hasattr(response, 'isError') and not response.isError():
                    return response
                elif hasattr(response, 'function_code'):
                    return response
                else:
                    self.logger.warning(f"Modbus error on attempt {attempt + 1}: {response}")
                    
            except Exception as e:
                self.logger.warning(f"Connection error on attempt {attempt + 1}: {e}")
                
            if attempt < max_retries - 1:
                sleep(0.1)  # Brief delay before retry
                
        self.error_count += 1
        return None

    def read_repose_signals(self, client, start_addr, count):
        """Read repose signals for alarm filtering"""
        try:
            response = self.read_with_retry(client, client.read_discrete_inputs, start_addr, count)
            if response and hasattr(response, 'bits'):
                return response.bits[:count]  # Ensure we don't exceed expected count
        except Exception as e:
            self.logger.error(f"Error reading repose signals at {start_addr}: {e}")
        
        return [False] * count  # Return safe defaults

    def collect_dg1_data(self, client):
        """Collect all DG1 data with comprehensive error handling"""
        success = True
        
        try:
            # Read DG1 Repose signals first (CORRECTED ADDRESS)
            repose_bits = self.read_repose_signals(client, 0x15, 5)
            for i, bit in enumerate(repose_bits):
                self.dg1_repose[f'RP{i+1}'] = bool(bit)
                
            # Read DG1 analog registers (CORRECTED ADDRESS)
            response = self.read_with_retry(client, client.read_input_registers, 0x01, 19)
            if response and hasattr(response, 'registers'):
                self.process_dg1_analog_data(response.registers)
            else:
                success = False
                
            # Read DG1 main discrete inputs (CORRECTED ADDRESS)
            response = self.read_with_retry(client, client.read_discrete_inputs, 0x01, 42)
            if response and hasattr(response, 'bits'):
                self.process_dg1_digital_data(response.bits)
            else:
                success = False
                
            # Read DG1 exhaust sensor failures (CORRECTED ADDRESS)
            response = self.read_with_retry(client, client.read_discrete_inputs, 0x7F, 6)
            if response and hasattr(response, 'bits'):
                self.process_dg1_exhaust_data(response.bits)
            else:
                success = False
                
        except Exception as e:
            self.logger.error(f"Error collecting DG1 data: {e}")
            success = False
            
        return success

    def process_dg1_analog_data(self, registers):
        """Process DG1 analog register values - storing the actual numeric values for CSV"""
        # Original code analysis: job() function must use the numeric values, not the string variables
        # The scaled numeric values (like L19ae) should be what gets written to CSV
        for i, register_value in enumerate(registers):
            if i < 19:  # Ensure we don't exceed expected count
                try:
                    if i == 0:  # 30003 - L.O. Engine inlet temp (raw register_value)
                        self.dg1_data['L1'] = register_value
                    elif i == 1:  # 30004 - C.F.W. eng outlet temp (raw register_value)
                        self.dg1_data['L2'] = register_value
                    elif i == 2:  # 30006 - Cyl1 exhaust temp (raw register_value)
                        self.dg1_data['L3'] = register_value
                    elif i == 3:  # 30007 - Cyl2 exhaust temp (raw register_value)
                        self.dg1_data['L4'] = register_value
                    elif i == 4:  # 30008 - Cyl3 exhaust temp (raw register_value)
                        self.dg1_data['L5'] = register_value
                    elif i == 5:  # 30009 - Cyl4 exhaust temp (raw register_value)
                        self.dg1_data['L6'] = register_value
                    elif i == 6:  # 30010 - Cyl5 exhaust temp (raw register_value)
                        self.dg1_data['L7'] = register_value
                    elif i == 7:  # 30011 - Cyl6 exhaust temp (raw register_value)
                        self.dg1_data['L8'] = register_value
                    elif i == 8:  # 30014 - T/C inlet 1 temp (raw register_value)
                        self.dg1_data['L9'] = register_value
                    elif i == 9:  # 30015 - T/C inlet 2 temp (raw register_value)
                        self.dg1_data['L10'] = register_value
                    elif i == 10:  # 30016 - T/C outlet temp (raw register_value)
                        self.dg1_data['L11'] = register_value
                    elif i == 11:  # 30017 - CFW inlet pressure (store L12ae equivalent)
                        self.dg1_data['L12'] = register_value * 0.01
                    elif i == 12:  # 30018 - Boost air pressure (store L13ae equivalent)
                        self.dg1_data['L13'] = register_value * 0.001
                    elif i == 13:  # 30020 - Start air pressure (store L14ae equivalent)
                        self.dg1_data['L14'] = register_value * 0.01
                    elif i == 14:  # 30021 - F.O. inlet pressure (store L15ae equivalent)
                        self.dg1_data['L15'] = register_value * 0.01
                    elif i == 15:  # 30025 - Lub oil pressure (store L16ae equivalent)
                        self.dg1_data['L16'] = register_value * 0.01
                    elif i == 16:  # 30026 - Engine speed (raw register_value)
                        self.dg1_data['L17'] = register_value
                    elif i == 17:  # 30028 - Engine load (raw register_value)
                        self.dg1_data['L18'] = register_value
                    elif i == 18:  # 30029 - Engine run hours (store L19ae equivalent)
                        self.dg1_data['L19'] = register_value * 10
                        
                except (IndexError, TypeError, ValueError) as e:
                    self.logger.warning(f"Error processing DG1 register {i}: {e}")

    def process_dg1_digital_data(self, bits):
        """Process DG1 digital input values with repose filtering - CORRECTED BIT MAPPING"""
        # With corrected address offset (0x01), bit mapping is now sequential from start
        digital_mapping = [
            ('C1', 0, True),   # 0x01 + 0 = 0x01 = 10001 - LO filter diff pressure (with repose filter)
            ('C2', 1, False),  # 0x01 + 1 = 0x02 = 10002 - Control air low pressure
            ('C3', 2, True),   # 0x01 + 2 = 0x03 = 10009 - T/C LO low pressure (with repose filter)
            ('C6', 3, False),  # 0x01 + 3 = 0x04 = 10012 - F.O. leaked and level high
            ('C7', 4, False),  # 0x01 + 4 = 0x05 = 10013 - L.O. sump tank level low
            ('C8', 5, False),  # 0x01 + 5 = 0x06 = 10017 - Engine running
            ('C9', 6, False),  # 0x01 + 6 = 0x07 = 10018 - Ready to start
            ('C10', 7, False), # 0x01 + 7 = 0x08 = 10019 - Over speed stop
            ('C11', 8, False), # 0x01 + 8 = 0x09 = 10020 - CFW outlet high temp stop
            ('C12', 9, False), # 0x01 + 9 = 0x0A = 10021 - L.O. inlet low pressure stop
            ('C13', 10, False),# 0x01 + 10 = 0x0B = 10023 - Emergency stop
            ('C14', 11, False),# 0x01 + 11 = 0x0C = 10024 - Start failure
            ('C15', 12, False),# 0x01 + 12 = 0x0D = 10025 - Pre LO pump motor failure
            ('C16', 13, True), # 0x01 + 13 = 0x0E = 10026 - Priming lub oil pressure (with repose filter)
            ('C17', 14, False),# 0x01 + 14 = 0x0F = 10027 - Pre LO pump running
            ('C18', 15, False),# 0x01 + 15 = 0x10 = 10033 - System failure
            ('C19', 16, False),# 0x01 + 16 = 0x11 = 10034 - Control module failure
            ('C20', 17, False),# 0x01 + 17 = 0x12 = 10035 - Safety module failure
            ('C21', 18, False),# 0x01 + 18 = 0x13 = 10036 - Link to engine display fail
            ('C22', 19, False),# 0x01 + 19 = 0x14 = 10037 - Link to remote I/O failure
            ('C23', 25, False),# 0x01 + 25 = 0x1A = 10059 - Emergency stop external
            ('C24', 26, False),# 0x01 + 26 = 0x1B = 10060 - Emergency stop ECD
            ('C25', 27, False),# 0x01 + 27 = 0x1C = 10061 - High temp CW temp switch fail
            ('C26', 28, False),# 0x01 + 28 = 0x1D = 10062 - Lub oil pressure switch failure
            ('C27', 29, False),# 0x01 + 29 = 0x1E = 10064 - Emergency stop solenoid fail
            ('C28', 30, False),# 0x01 + 30 = 0x1F = 10067 - LO engine temp sensor fail
            ('C29', 31, False),# 0x01 + 31 = 0x20 = 10068 - HT CW temp sensor fail
            ('C30', 32, False),# 0x01 + 32 = 0x21 = 10078 - Exhaust TC in 1 temp sensor fail
            ('C31', 33, False),# 0x01 + 33 = 0x22 = 10079 - Exhaust TC in 2 temp sensor fail
            ('C32', 34, False),# 0x01 + 34 = 0x23 = 10080 - Exhaust TC out temp sensor fail
            ('C33', 35, False),# 0x01 + 35 = 0x24 = 10081 - HT CW pressure sensor fail
            ('C34', 36, False),# 0x01 + 36 = 0x25 = 10082 - Boost air pressure sensor fail
            ('C35', 37, False),# 0x01 + 37 = 0x26 = 10084 - Start air pressure sensor fail
            ('C36', 38, False),# 0x01 + 38 = 0x27 = 10085 - F.O. inlet pressure sensor fail
            ('C37', 39, False),# 0x01 + 39 = 0x28 = 10089 - L.O. pressure sensor fail
            ('C38', 40, False),# 0x01 + 40 = 0x29 = 10090 - Speed pickup sensor failure
            ('C39', 41, False) # 0x01 + 41 = 0x2A = 10091 - Load input failure
        ]
        
        for var_name, bit_index, use_repose in digital_mapping:
            try:
                if bit_index < len(bits):
                    bit_value = bool(bits[bit_index])
                    
                    # Apply repose filtering if needed
                    if use_repose:
                        if var_name == 'C1':  # LO filter diff pressure
                            filtered_value = bit_value and not self.dg1_repose.get('RP5', False)
                        elif var_name == 'C3':  # T/C LO low pressure
                            filtered_value = bit_value and not self.dg1_repose.get('RP2', False)
                        elif var_name == 'C16':  # Priming lub oil pressure
                            filtered_value = bit_value and not self.dg1_repose.get('RP3', False)
                        else:
                            filtered_value = bit_value
                            
                        self.dg1_data[var_name] = int(filtered_value)
                    else:
                        self.dg1_data[var_name] = int(bit_value)
                        
            except (IndexError, TypeError) as e:
                self.logger.warning(f"Error processing DG1 digital bit {bit_index}: {e}")

    def process_dg1_exhaust_data(self, bits):
        """Process DG1 exhaust sensor failure data"""
        exhaust_mapping = ['C40', 'C41', 'C42', 'C43', 'C44', 'C45']
        
        for i, var_name in enumerate(exhaust_mapping):
            try:
                if i < len(bits):
                    self.dg1_data[var_name] = int(bool(bits[i]))
            except (IndexError, TypeError) as e:
                self.logger.warning(f"Error processing DG1 exhaust bit {i}: {e}")

    def collect_dg2_data(self, client):
        """Collect all DG2 data with comprehensive error handling"""
        success = True
        
        try:
            # Read DG2 Repose signals (CORRECTED ADDRESS)
            repose_bits = self.read_repose_signals(client, 0x3F, 5)
            for i, bit in enumerate(repose_bits):
                self.dg2_repose[f'SP{i+1}'] = bool(bit)
                
            # Read DG2 analog registers (CORRECTED ADDRESS)
            response = self.read_with_retry(client, client.read_input_registers, 0x14, 19)
            if response and hasattr(response, 'registers'):
                self.process_dg2_analog_data(response.registers)
            else:
                success = False
                
            # Read DG2 discrete inputs (CORRECTED ADDRESS)
            response = self.read_with_retry(client, client.read_discrete_inputs, 0x2B, 42)
            if response and hasattr(response, 'bits'):
                self.process_dg2_digital_data(response.bits)
            else:
                success = False
                
            # Read DG2 exhaust sensor failures (CORRECTED ADDRESS)
            response = self.read_with_retry(client, client.read_discrete_inputs, 0x85, 6)
            if response and hasattr(response, 'bits'):
                self.process_dg2_exhaust_data(response.bits)
            else:
                success = False
                
        except Exception as e:
            self.logger.error(f"Error collecting DG2 data: {e}")
            success = False
            
        return success

    def process_dg2_analog_data(self, registers):
        """Process DG2 analog register values exactly matching original code scaling"""
        # Store the SCALED values that job1() function expects to write to CSV
        for i, register_value in enumerate(registers):
            if i < 19:  # Ensure we don't exceed expected count
                try:
                    if i == 0:  # 30003 - L.O. Engine inlet temp (no scaling)
                        self.dg2_data['K1'] = register_value
                    elif i == 1:  # 30004 - C.F.W. eng outlet temp (no scaling)
                        self.dg2_data['K2'] = register_value
                    elif i == 2:  # 30006 - Cyl1 exhaust temp (no scaling)
                        self.dg2_data['K3'] = register_value
                    elif i == 3:  # 30007 - Cyl2 exhaust temp (no scaling)
                        self.dg2_data['K4'] = register_value
                    elif i == 4:  # 30008 - Cyl3 exhaust temp (no scaling)
                        self.dg2_data['K5'] = register_value
                    elif i == 5:  # 30009 - Cyl4 exhaust temp (no scaling)
                        self.dg2_data['K6'] = register_value
                    elif i == 6:  # 30010 - Cyl5 exhaust temp (no scaling)
                        self.dg2_data['K7'] = register_value
                    elif i == 7:  # 30011 - Cyl6 exhaust temp (no scaling)
                        self.dg2_data['K8'] = register_value
                    elif i == 8:  # 30014 - T/C inlet 1 temp (no scaling)
                        self.dg2_data['K9'] = register_value
                    elif i == 9:  # 30015 - T/C inlet 2 temp (no scaling)
                        self.dg2_data['K10'] = register_value
                    elif i == 10:  # 30016 - T/C outlet temp (no scaling)
                        self.dg2_data['K11'] = register_value
                    elif i == 11:  # 30017 - CFW inlet pressure (K12ae = register_value1 * 0.01)
                        self.dg2_data['K12'] = register_value * 0.01
                    elif i == 12:  # 30018 - Boost air pressure (K13ae = register_value1 * 0.001)
                        self.dg2_data['K13'] = register_value * 0.001
                    elif i == 13:  # 30020 - Start air pressure (K14ae = register_value1 * 0.01)
                        self.dg2_data['K14'] = register_value * 0.01
                    elif i == 14:  # 30021 - F.O. inlet pressure (K15ae = register_value1 * 0.01)
                        self.dg2_data['K15'] = register_value * 0.01
                    elif i == 15:  # 30025 - Lub oil pressure (K16ae = register_value1 * 0.01)
                        self.dg2_data['K16'] = register_value * 0.01
                    elif i == 16:  # 30026 - Engine speed (no scaling)
                        self.dg2_data['K17'] = register_value
                    elif i == 17:  # 30028 - Engine load (no scaling)
                        self.dg2_data['K18'] = register_value
                    elif i == 18:  # 30029 - Engine run hours (K19ae = register_value1 * 10)
                        self.dg2_data['K19'] = register_value * 10
                        
                except (IndexError, TypeError, ValueError) as e:
                    self.logger.warning(f"Error processing DG2 register {i}: {e}")

    def process_dg2_digital_data(self, bits):
        """Process DG2 digital input values with repose filtering - CORRECTED BIT MAPPING"""
        # With corrected address offset (0x2B), bit mapping is sequential from start
        digital_mapping = [
            ('B1', 0, True),   # 0x2B + 0 = 0x2B = 10001 - LO filter diff pressure (with repose filter)
            ('B2', 1, False),  # 0x2B + 1 = 0x2C = 10002 - Control air low pressure
            ('B3', 2, True),   # 0x2B + 2 = 0x2D = 10009 - T/C LO low pressure (with repose filter)
            ('B6', 3, False),  # 0x2B + 3 = 0x2E = 10012 - F.O. leaked and level high
            ('B7', 4, False),  # 0x2B + 4 = 0x2F = 10013 - L.O. sump tank level low
            ('B8', 5, False),  # 0x2B + 5 = 0x30 = 10017 - Engine running
            ('B9', 6, False),  # 0x2B + 6 = 0x31 = 10018 - Ready to start
            ('B10', 7, False), # 0x2B + 7 = 0x32 = 10019 - Over speed stop
            ('B11', 8, False), # 0x2B + 8 = 0x33 = 10020 - CFW outlet high temp stop
            ('B12', 9, False), # 0x2B + 9 = 0x34 = 10021 - L.O. inlet low pressure stop
            ('B13', 10, False),# 0x2B + 10 = 0x35 = 10023 - Emergency stop
            ('B14', 11, False),# 0x2B + 11 = 0x36 = 10024 - Start failure
            ('B15', 12, False),# 0x2B + 12 = 0x37 = 10025 - Pre LO pump motor failure
            ('B16', 13, True), # 0x2B + 13 = 0x38 = 10026 - Priming lub oil pressure (with repose filter)
            ('B17', 14, False),# 0x2B + 14 = 0x39 = 10027 - Pre LO pump running
            ('B18', 15, False),# 0x2B + 15 = 0x3A = 10033 - System failure
            ('B19', 16, False),# 0x2B + 16 = 0x3B = 10034 - Control module failure
            ('B20', 17, False),# 0x2B + 17 = 0x3C = 10035 - Safety module failure
            ('B21', 18, False),# 0x2B + 18 = 0x3D = 10036 - Link to engine display fail
            ('B22', 19, False),# 0x2B + 19 = 0x3E = 10037 - Link to remote I/O failure
            ('B23', 25, False),# 0x2B + 25 = 0x44 = 10059 - Emergency stop external
            ('B24', 26, False),# 0x2B + 26 = 0x45 = 10060 - Emergency stop ECD
            ('B25', 27, False),# 0x2B + 27 = 0x46 = 10061 - High temp CW temp switch fail
            ('B26', 28, False),# 0x2B + 28 = 0x47 = 10062 - Lub oil pressure switch failure
            ('B27', 29, False),# 0x2B + 29 = 0x48 = 10064 - Emergency stop solenoid fail
            ('B28', 30, False),# 0x2B + 30 = 0x49 = 10067 - LO engine temp sensor fail
            ('B29', 31, False),# 0x2B + 31 = 0x4A = 10068 - HT CW temp sensor fail
            ('B30', 32, False),# 0x2B + 32 = 0x4B = 10078 - Exhaust TC in 1 temp sensor fail
            ('B31', 33, False),# 0x2B + 33 = 0x4C = 10079 - Exhaust TC in 2 temp sensor fail
            ('B32', 34, False),# 0x2B + 34 = 0x4D = 10080 - Exhaust TC out temp sensor fail
            ('B33', 35, False),# 0x2B + 35 = 0x4E = 10081 - HT CW pressure sensor fail
            ('B34', 36, False),# 0x2B + 36 = 0x4F = 10082 - Boost air pressure sensor fail
            ('B35', 37, False),# 0x2B + 37 = 0x50 = 10084 - Start air pressure sensor fail
            ('B36', 38, False),# 0x2B + 38 = 0x51 = 10085 - F.O. inlet pressure sensor fail
            ('B37', 39, False),# 0x2B + 39 = 0x52 = 10089 - L.O. pressure sensor fail
            ('B38', 40, False),# 0x2B + 40 = 0x53 = 10090 - Speed pickup sensor failure
            ('B39', 41, False) # 0x2B + 41 = 0x54 = 10091 - Load input failure
        ]
        
        for var_name, bit_index, use_repose in digital_mapping:
            try:
                if bit_index < len(bits):
                    bit_value = bool(bits[bit_index])
                    
                    if use_repose:
                        if var_name == 'B1':  # LO filter diff pressure
                            filtered_value = bit_value and not self.dg2_repose.get('SP5', False)
                        elif var_name == 'B3':  # T/C LO low pressure
                            filtered_value = bit_value and not self.dg2_repose.get('SP2', False)
                        elif var_name == 'B16':  # Priming lub oil pressure
                            filtered_value = bit_value and not self.dg2_repose.get('SP3', False)
                        else:
                            filtered_value = bit_value
                            
                        self.dg2_data[var_name] = int(filtered_value)
                    else:
                        self.dg2_data[var_name] = int(bit_value)
                        
            except (IndexError, TypeError) as e:
                self.logger.warning(f"Error processing DG2 digital bit {bit_index}: {e}")

    def process_dg2_exhaust_data(self, bits):
        """Process DG2 exhaust sensor failure data"""
        exhaust_mapping = ['B40', 'B41', 'B42', 'B43', 'B44', 'B45']
        
        for i, var_name in enumerate(exhaust_mapping):
            try:
                if i < len(bits):
                    self.dg2_data[var_name] = int(bool(bits[i]))
            except (IndexError, TypeError) as e:
                self.logger.warning(f"Error processing DG2 exhaust bit {i}: {e}")

    def collect_dg3_data(self, client):
        """Collect all DG3 data with comprehensive error handling"""
        success = True
        
        try:
            # Read DG3 Repose signals (CORRECTED ADDRESS)
            repose_bits = self.read_repose_signals(client, 0x69, 5)
            for i, bit in enumerate(repose_bits):
                self.dg3_repose[f'TP{i+1}'] = bool(bit)
                
            # Read DG3 analog registers (CORRECTED ADDRESS)
            response = self.read_with_retry(client, client.read_input_registers, 0x27, 19)
            if response and hasattr(response, 'registers'):
                self.process_dg3_analog_data(response.registers)
            else:
                success = False
                
            # Read DG3 discrete inputs (CORRECTED ADDRESS)
            response = self.read_with_retry(client, client.read_discrete_inputs, 0x55, 42)
            if response and hasattr(response, 'bits'):
                self.process_dg3_digital_data(response.bits)
            else:
                success = False
                
            # Read DG3 exhaust sensor failures (CORRECTED ADDRESS)
            response = self.read_with_retry(client, client.read_discrete_inputs, 0x8B, 6)
            if response and hasattr(response, 'bits'):
                self.process_dg3_exhaust_data(response.bits)
            else:
                success = False
                
        except Exception as e:
            self.logger.error(f"Error collecting DG3 data: {e}")
            success = False
            
        return success

    def process_dg3_analog_data(self, registers):
        """Process DG3 analog register values exactly matching original code scaling"""
        # Store the SCALED values that job2() function expects to write to CSV
        for i, register_value in enumerate(registers):
            if i < 19:  # Ensure we don't exceed expected count
                try:
                    if i == 0:  # 30003 - L.O. Engine inlet temp (no scaling)
                        self.dg3_data['J1'] = register_value
                    elif i == 1:  # 30004 - C.F.W. eng outlet temp (no scaling)
                        self.dg3_data['J2'] = register_value
                    elif i == 2:  # 30006 - Cyl1 exhaust temp (no scaling)
                        self.dg3_data['J3'] = register_value
                    elif i == 3:  # 30007 - Cyl2 exhaust temp (no scaling)
                        self.dg3_data['J4'] = register_value
                    elif i == 4:  # 30008 - Cyl3 exhaust temp (no scaling)
                        self.dg3_data['J5'] = register_value
                    elif i == 5:  # 30009 - Cyl4 exhaust temp (no scaling)
                        self.dg3_data['J6'] = register_value
                    elif i == 6:  # 30010 - Cyl5 exhaust temp (no scaling)
                        self.dg3_data['J7'] = register_value
                    elif i == 7:  # 30011 - Cyl6 exhaust temp (no scaling)
                        self.dg3_data['J8'] = register_value
                    elif i == 8:  # 30014 - T/C inlet 1 temp (no scaling)
                        self.dg3_data['J9'] = register_value
                    elif i == 9:  # 30015 - T/C inlet 2 temp (no scaling)
                        self.dg3_data['J10'] = register_value
                    elif i == 10:  # 30016 - T/C outlet temp (no scaling)
                        self.dg3_data['J11'] = register_value
                    elif i == 11:  # 30017 - CFW inlet pressure (J12ae = register_value2 * 0.01)
                        self.dg3_data['J12'] = register_value * 0.01
                    elif i == 12:  # 30018 - Boost air pressure (J13ae = register_value2 * 0.001)
                        self.dg3_data['J13'] = register_value * 0.001
                    elif i == 13:  # 30020 - Start air pressure (J14ae = register_value2 * 0.01)
                        self.dg3_data['J14'] = register_value * 0.01
                    elif i == 14:  # 30021 - F.O. inlet pressure (J15ae = register_value2 * 0.01)
                        self.dg3_data['J15'] = register_value * 0.01
                    elif i == 15:  # 30025 - Lub oil pressure (J16ae = register_value2 * 0.01)
                        self.dg3_data['J16'] = register_value * 0.01
                    elif i == 16:  # 30026 - Engine speed (no scaling)
                        self.dg3_data['J17'] = register_value
                    elif i == 17:  # 30028 - Engine load (no scaling)
                        self.dg3_data['J18'] = register_value
                    elif i == 18:  # 30029 - Engine run hours (J19ae = register_value2 * 10)
                        self.dg3_data['J19'] = register_value * 10
                        
                except (IndexError, TypeError, ValueError) as e:
                    self.logger.warning(f"Error processing DG3 register {i}: {e}")

    def process_dg3_digital_data(self, bits):
        """Process DG3 digital input values with repose filtering - CORRECTED BIT MAPPING"""
        # With corrected address offset (0x55), bit mapping is sequential from start
        digital_mapping = [
            ('A1', 0, True),   # 0x55 + 0 = 0x55 = 10001 - LO filter diff pressure (with repose filter)
            ('A2', 1, False),  # 0x55 + 1 = 0x56 = 10002 - Control air low pressure
            ('A3', 2, True),   # 0x55 + 2 = 0x57 = 10009 - T/C LO low pressure (with repose filter)
            ('A6', 3, False),  # 0x55 + 3 = 0x58 = 10012 - F.O. leaked and level high
            ('A7', 4, False),  # 0x55 + 4 = 0x59 = 10013 - L.O. sump tank level low
            ('A8', 5, False),  # 0x55 + 5 = 0x5A = 10017 - Engine running
            ('A9', 6, False),  # 0x55 + 6 = 0x5B = 10018 - Ready to start
            ('A10', 7, False), # 0x55 + 7 = 0x5C = 10019 - Over speed stop
            ('A11', 8, False), # 0x55 + 8 = 0x5D = 10020 - CFW outlet high temp stop
            ('A12', 9, False), # 0x55 + 9 = 0x5E = 10021 - L.O. inlet low pressure stop
            ('A13', 10, False),# 0x55 + 10 = 0x5F = 10023 - Emergency stop
            ('A14', 11, False),# 0x55 + 11 = 0x60 = 10024 - Start failure
            ('A15', 12, False),# 0x55 + 12 = 0x61 = 10025 - Pre LO pump motor failure
            ('A16', 13, True), # 0x55 + 13 = 0x62 = 10026 - Priming lub oil pressure (with repose filter)
            ('A17', 14, False),# 0x55 + 14 = 0x63 = 10027 - Pre LO pump running
            ('A18', 15, False),# 0x55 + 15 = 0x64 = 10033 - System failure
            ('A19', 16, False),# 0x55 + 16 = 0x65 = 10034 - Control module failure
            ('A20', 17, False),# 0x55 + 17 = 0x66 = 10035 - Safety module failure
            ('A21', 18, False),# 0x55 + 18 = 0x67 = 10036 - Link to engine display fail
            ('A22', 19, False),# 0x55 + 19 = 0x68 = 10037 - Link to remote I/O failure
            ('A23', 25, False),# 0x55 + 25 = 0x6E = 10059 - Emergency stop external
            ('A24', 26, False),# 0x55 + 26 = 0x6F = 10060 - Emergency stop ECD
            ('A25', 27, False),# 0x55 + 27 = 0x70 = 10061 - High temp CW temp switch fail
            ('A26', 28, False),# 0x55 + 28 = 0x71 = 10062 - Lub oil pressure switch failure
            ('A27', 29, False),# 0x55 + 29 = 0x72 = 10064 - Emergency stop solenoid fail
            ('A28', 30, False),# 0x55 + 30 = 0x73 = 10067 - LO engine temp sensor fail
            ('A29', 31, False),# 0x55 + 31 = 0x74 = 10068 - HT CW temp sensor fail
            ('A30', 32, False),# 0x55 + 32 = 0x75 = 10078 - Exhaust TC in 1 temp sensor fail
            ('A31', 33, False),# 0x55 + 33 = 0x76 = 10079 - Exhaust TC in 2 temp sensor fail
            ('A32', 34, False),# 0x55 + 34 = 0x77 = 10080 - Exhaust TC out temp sensor fail
            ('A33', 35, False),# 0x55 + 35 = 0x78 = 10081 - HT CW pressure sensor fail
            ('A34', 36, False),# 0x55 + 36 = 0x79 = 10082 - Boost air pressure sensor fail
            ('A35', 37, False),# 0x55 + 37 = 0x7A = 10084 - Start air pressure sensor fail
            ('A36', 38, False),# 0x55 + 38 = 0x7B = 10085 - F.O. inlet pressure sensor fail
            ('A37', 39, False),# 0x55 + 39 = 0x7C = 10089 - L.O. pressure sensor fail
            ('A38', 40, False),# 0x55 + 40 = 0x7D = 10090 - Speed pickup sensor failure
            ('A39', 41, False) # 0x55 + 41 = 0x7E = 10091 - Load input failure
        ]
        
        for var_name, bit_index, use_repose in digital_mapping:
            try:
                if bit_index < len(bits):
                    bit_value = bool(bits[bit_index])
                    
                    if use_repose:
                        if var_name == 'A1':  # LO filter diff pressure
                            filtered_value = bit_value and not self.dg3_repose.get('TP5', False)
                        elif var_name == 'A3':  # T/C LO low pressure
                            filtered_value = bit_value and not self.dg3_repose.get('TP2', False)
                        elif var_name == 'A16':  # Priming lub oil pressure
                            filtered_value = bit_value and not self.dg3_repose.get('TP3', False)
                        else:
                            filtered_value = bit_value
                            
                        self.dg3_data[var_name] = int(filtered_value)
                    else:
                        self.dg3_data[var_name] = int(bit_value)
                        
            except (IndexError, TypeError) as e:
                self.logger.warning(f"Error processing DG3 digital bit {bit_index}: {e}")

    def process_dg3_exhaust_data(self, bits):
        """Process DG3 exhaust sensor failure data"""
        exhaust_mapping = ['A40', 'A41', 'A42', 'A43', 'A44', 'A45']
        
        for i, var_name in enumerate(exhaust_mapping):
            try:
                if i < len(bits):
                    self.dg3_data[var_name] = int(bool(bits[i]))
            except (IndexError, TypeError) as e:
                self.logger.warning(f"Error processing DG3 exhaust bit {i}: {e}")

    def collect_all_data(self):
        """Master data collection function - collects all DG data atomically"""
        if self.collection_in_progress:
            self.logger.warning("Data collection already in progress, skipping...")
            return False
            
        self.collection_in_progress = True
        collection_success = False
        
        try:
            with self.data_lock:
                client = self.create_modbus_connection()
                if not client:
                    self.logger.error("Failed to create Modbus connection")
                    return False
                
                try:
                    # Collect data from all three DGs
                    dg1_success = self.collect_dg1_data(client)
                    dg2_success = self.collect_dg2_data(client)
                    dg3_success = self.collect_dg3_data(client)
                    
                    collection_success = dg1_success and dg2_success and dg3_success
                    
                    if collection_success:
                        self.collection_count += 1
                        self.last_collection_time = datetime.datetime.now()
                        self.logger.info(f"Data collection #{self.collection_count} completed successfully")
                    else:
                        self.logger.warning("Partial data collection failure")
                        
                finally:
                    client.close()
                    
        except Exception as e:
            self.logger.error(f"Critical error during data collection: {e}")
            collection_success = False
        finally:
            self.collection_in_progress = False
            
        return collection_success

    def write_dg1_csv(self):
        """Write DG1 data to CSV with thread safety, channel descriptions and timestamps"""
        dt = datetime.datetime.now()
        timestamp_str = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        logfile = f'/home/drums/csv/MOD_NDY1274_DG_1-{dt.year}-{dt.month}-{dt.day}-{dt.hour}-{dt.minute}.csv'
        
        try:
            with self.data_lock:
                with open(logfile, "a") as log:
                    # Channel mappings with descriptions from original code
                    analog_channels = [
                        ("30003", "L1", "NO.1 DG L.O. ENGINE INLET HIGH TEMP. ALA", "deg C"),
                        ("30004", "L2", "NO.1 DG C.F.W. ENG. OUTLET HIGH TEMP ALA", "deg C"),
                        ("30006", "L3", "NO.1 DG CYL1 EXH. GAS TEMP.", "deg C"),
                        ("30007", "L4", "NO.1 DG CYL2 EXH. GAS TEMP.", "deg C"),
                        ("30008", "L5", "NO.1 DG CYL3 EXH. GAS TEMP.", "deg C"),
                        ("30009", "L6", "NO.1 DG CYL4 EXH. GAS TEMP.", "deg C"),
                        ("30010", "L7", "NO.1 DG CYL5 EXH. GAS TEMP.", "deg C"),
                        ("30011", "L8", "NO.1 DG CYL6 EXH. GAS TEMP.", "deg C"),
                        ("30014", "L9", "NO.1 DG EXH. GAS T/C INLET 1 TEMP", "deg C"),
                        ("30015", "L10", "NO.1 DG EXH. GAS T/C INLET 2 TEMP H", "deg C"),
                        ("30016", "L11", "NO.1 DG EXH. GAS TEMP. T/C OUTLET", "deg C"),
                        ("30017", "L12", "NO.1 DG C.F.W. ENG. INLET LOW PRESS. ALA", "MPa"),
                        ("30018", "L13", "NO.1 DG BOOST AIR PRESS.", "MPa"),
                        ("30020", "L14", "NO.1 DG START AIR LOW PRESS. ALARM", "MPa"),
                        ("30021", "L15", "NO.1 DG F.O. PRESS. INLET", "MPa"),
                        ("30025", "L16", "NO.1 DG LUB OIL LOW PRESS ALARM", "MPa"),
                        ("30026", "L17", "NO.1 DG ENGINE SPEED", "min-1"),
                        ("30028", "L18", "NO.1 DG ENGINE LOAD", "kW"),
                        ("30029", "L19", "NO.1 DG ENGINE RUNNING HOUR", "10xHour")
                    ]
                    
                    digital_channels = [
                        ("10001", "C1", "NO.1 DG LO ENG INLET FILTER DIFF. PRE. H"),
                        ("10002", "C2", "NO.1 DG CONTROL AIR LOW PRESS. ALARM"),
                        ("10009", "C3", "NO.1 DG T/C LO. LOW PRESS. ALARM"),
                        ("10012", "C6", "NO.1 DG F.O. LEAKED AND LEVEL HIGH ALARM"),
                        ("10013", "C7", "NO.1 DG L.O. SUMP TANK LEVEL LOW ALARM"),
                        ("10017", "C8", "NO.1 DG ENGINE RUNNING"),
                        ("10018", "C9", "NO.1 DG READY TO START"),
                        ("10019", "C10", "NO.1 DG OVER SPEED (STOP)"),
                        ("10020", "C11", "NO.1 DG CFW. ENG. OUTLET HIGH TEMP. STOP"),
                        ("10021", "C12", "NO.1 DG L.O. INLET LOW PRESS. LOW STOP"),
                        ("10023", "C13", "NO.1 DG EMERGENCY STOP(REMOTE/LOCAL)"),
                        ("10024", "C14", "NO.1 DG START FAILURE"),
                        ("10025", "C15", "NO.1 DG PRE. LO. PUMP MOTOR FAILURE (Thermal)"),
                        ("10026", "C16", "NO.1 DG PRIMING LUB OIL PRESS.LOW ALARM"),
                        ("10027", "C17", "NO.1 DG PRE. LO. PUMP  RUNNING"),
                        ("10033", "C18", "NO.1 DG SYSTEM FAILURE"),
                        ("10034", "C19", "NO.1 DG CONTROL MODULE FAILURE"),
                        ("10035", "C20", "NO.1 DG SAFETY MODULE FAILURE"),
                        ("10036", "C21", "NO.1 DG LINK TO ENGINE COND DISPLAY FAIL"),
                        ("10037", "C22", "NO.1 DG LINK TO REMOTE I/O-1 FAILURE"),
                        ("10059", "C23", "NO.1 DG EM'CY STOP SWITCH OF EXTERNAL"),
                        ("10060", "C24", "NO.1 DG EM'CY STOP SWITCH OF ECD"),
                        ("10061", "C25", "NO.1 DG HIGH TEMP C.W. TEMP. SWITCH FAIL"),
                        ("10062", "C26", "NO.1 DG LUB.OIL PRESS. SWITCH FAILURE"),
                        ("10064", "C27", "NO.1 DG EM'CY STOP SOLENOID VALVE FAIL"),
                        ("10067", "C28", "NO.1 DG L.O. ENGINE IN TEMP SENSOR FAIL"),
                        ("10068", "C29", "NO.1 DG H.T. C. W. OUT. TEMP SENSOR FAIL"),
                        ("10078", "C30", "NO.1 DG EXH GAS TC IN 1 TEMP SENSOR FAIL"),
                        ("10079", "C31", "NO.1 DG EXH GAS TC IN 2 TEMP SENSOR FAIL"),
                        ("10080", "C32", "NO.1 DG EXH. GAS TC OUT TEMP SENSOR FAIL"),
                        ("10081", "C33", "NO.1 DG H.T. C.W. PRESS IN SENSOR FAIL"),
                        ("10082", "C34", "NO.1 DG BOOST AIR PRESS. SENSOR FAIL"),
                        ("10084", "C35", "NO.1 DG STARTING AIR PRESS. SENSOR FAIL"),
                        ("10085", "C36", "NO.1 DG F.O. INLET PRESS SENSOR FAIL"),
                        ("10089", "C37", "NO.1 DG L.O. IN. PRESS. SENSOR FAIL"),
                        ("10090", "C38", "NO.1 DG ALL SPEED PICKUP SENSOR FAILURE"),
                        ("10091", "C39", "NO.1 DG LOAD INPUT FAILURE"),
                        ("10070", "C40", "NO.1 DG CYL.1 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10071", "C41", "NO.1 DG CYL.2 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10072", "C42", "NO.1 DG CYL.3 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10073", "C43", "NO.1 DG CYL.4 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10074", "C44", "NO.1 DG CYL.5 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10075", "C45", "NO.1 DG CYL.6 EXH. GAS TEMP. SENSOR FAIL")
                    ]
                    
                    # Write analog data with descriptions and timestamps
                    for channel, var_name, description, unit in analog_channels:
                        value = self.dg1_data.get(var_name, 0)
                        log.write(f"{self.imo_no},{self.dg1_serial},{channel},{description},{timestamp_str},{value},{unit}\n")
                    
                    # Write digital data with descriptions and timestamps
                    for channel, var_name, description in digital_channels:
                        value = self.dg1_data.get(var_name, 0)
                        log.write(f"{self.imo_no},{self.dg1_serial},{channel},{description},{timestamp_str},{value},ON/OFF\n")
                        
        except Exception as e:
            self.logger.error(f"Error writing DG1 CSV: {e}")

    def write_dg2_csv(self):
        """Write DG2 data to CSV with thread safety, channel descriptions and timestamps"""
        dt = datetime.datetime.now()
        timestamp_str = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        logfile = f'/home/drums/csv/MOD_NDY1274_DG_2-{dt.year}-{dt.month}-{dt.day}-{dt.hour}-{dt.minute}.csv'
        
        try:
            with self.data_lock:
                with open(logfile, "a") as log:
                    # Channel mappings with descriptions for DG2
                    analog_channels = [
                        ("30003", "K1", "NO.2 DG L.O. ENGINE INLET HIGH TEMP. ALA", "deg C"),
                        ("30004", "K2", "NO.2 DG C.F.W. ENG. OUTLET HIGH TEMP ALA", "deg C"),
                        ("30006", "K3", "NO.2 DG CYL1 EXH. GAS TEMP.", "deg C"),
                        ("30007", "K4", "NO.2 DG CYL2 EXH. GAS TEMP.", "deg C"),
                        ("30008", "K5", "NO.2 DG CYL3 EXH. GAS TEMP.", "deg C"),
                        ("30009", "K6", "NO.2 DG CYL4 EXH. GAS TEMP.", "deg C"),
                        ("30010", "K7", "NO.2 DG CYL5 EXH. GAS TEMP.", "deg C"),
                        ("30011", "K8", "NO.2 DG CYL6 EXH. GAS TEMP.", "deg C"),
                        ("30014", "K9", "NO.2 DG EXH. GAS T/C INLET 1 TEMP", "deg C"),
                        ("30015", "K10", "NO.2 DG EXH. GAS T/C INLET 2 TEMP H", "deg C"),
                        ("30016", "K11", "NO.2 DG EXH. GAS TEMP. T/C OUTLET", "deg C"),
                        ("30017", "K12", "NO.2 DG C.F.W. ENG. INLET LOW PRESS. ALA", "MPa"),
                        ("30018", "K13", "NO.2 DG BOOST AIR PRESS.", "MPa"),
                        ("30020", "K14", "NO.2 DG START AIR LOW PRESS. ALARM", "MPa"),
                        ("30021", "K15", "NO.2 DG F.O. PRESS. INLET", "MPa"),
                        ("30025", "K16", "NO.2 DG LUB OIL LOW PRESS ALARM", "MPa"),
                        ("30026", "K17", "NO.2 DG ENGINE SPEED", "min-1"),
                        ("30028", "K18", "NO.2 DG ENGINE LOAD", "kW"),
                        ("30029", "K19", "NO.2 DG ENGINE RUNNING HOUR", "10xHour")
                    ]
                    
                    digital_channels = [
                        ("10001", "B1", "NO.2 DG LO ENG INLET FILTER DIFF. PRE. H"),
                        ("10002", "B2", "NO.2 DG CONTROL AIR LOW PRESS. ALARM"),
                        ("10009", "B3", "NO.2 DG T/C LO. LOW PRESS. ALARM"),
                        ("10012", "B6", "NO.2 DG F.O. LEAKED AND LEVEL HIGH ALARM"),
                        ("10013", "B7", "NO.2 DG L.O. SUMP TANK LEVEL LOW ALARM"),
                        ("10017", "B8", "NO.2 DG ENGINE RUNNING"),
                        ("10018", "B9", "NO.2 DG READY TO START"),
                        ("10019", "B10", "NO.2 DG OVER SPEED (STOP)"),
                        ("10020", "B11", "NO.2 DG CFW. ENG. OUTLET HIGH TEMP. STOP"),
                        ("10021", "B12", "NO.2 DG L.O. INLET LOW PRESS. LOW STOP"),
                        ("10023", "B13", "NO.2 DG EMERGENCY STOP(REMOTE/LOCAL)"),
                        ("10024", "B14", "NO.2 DG START FAILURE"),
                        ("10025", "B15", "NO.2 DG PRE. LO. PUMP MOTOR FAILURE (Thermal)"),
                        ("10026", "B16", "NO.2 DG PRIMING LUB OIL PRESS.LOW ALARM"),
                        ("10027", "B17", "NO.2 DG PRE. LO. PUMP RUNNING"),
                        ("10033", "B18", "NO.2 DG SYSTEM FAILURE"),
                        ("10034", "B19", "NO.2 DG CONTROL MODULE FAILURE"),
                        ("10035", "B20", "NO.2 DG SAFETY MODULE FAILURE"),
                        ("10036", "B21", "NO.2 DG LINK TO ENGINE COND DISPLAY FAIL"),
                        ("10037", "B22", "NO.2 DG LINK TO REMOTE I/O-1 FAILURE"),
                        ("10059", "B23", "NO.2 DG EM'CY STOP SWITCH OF EXTERNAL"),
                        ("10060", "B24", "NO.2 DG EM'CY STOP SWITCH OF ECD"),
                        ("10061", "B25", "NO.2 DG HIGH TEMP C.W. TEMP. SWITCH FAIL"),
                        ("10062", "B26", "NO.2 DG LUB.OIL PRESS. SWITCH FAILURE"),
                        ("10064", "B27", "NO.2 DG EM'CY STOP SOLENOID VALVE FAIL"),
                        ("10067", "B28", "NO.2 DG L.O. ENGINE IN TEMP SENSOR FAIL"),
                        ("10068", "B29", "NO.2 DG H.T. C.W. OUT. TEMP SENSOR FAIL"),
                        ("10078", "B30", "NO.2 DG EXH GAS TC IN 1 TEMP SENSOR FAIL"),
                        ("10079", "B31", "NO.2 DG EXH GAS TC IN 2 TEMP SENSOR FAIL"),
                        ("10080", "B32", "NO.2 DG EXH. GAS TC OUT TEMP SENSOR FAIL"),
                        ("10081", "B33", "NO.2 DG H.T. C.W. PRESS IN SENSOR FAIL"),
                        ("10082", "B34", "NO.2 DG BOOST AIR PRESS. SENSOR FAIL"),
                        ("10084", "B35", "NO.2 DG STARTING AIR PRESS. SENSOR FAIL"),
                        ("10085", "B36", "NO.2 DG F.O. INLET PRESS SENSOR FAIL"),
                        ("10089", "B37", "NO.2 DG L.O. IN. PRESS. SENSOR FAIL"),
                        ("10090", "B38", "NO.2 DG ALL SPEED PICKUP SENSOR FAILURE"),
                        ("10091", "B39", "NO.2 DG LOAD INPUT FAILURE"),
                        ("10070", "B40", "NO.2 DG CYL.1 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10071", "B41", "NO.2 DG CYL.2 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10072", "B42", "NO.2 DG CYL.3 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10073", "B43", "NO.2 DG CYL.4 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10074", "B44", "NO.2 DG CYL.5 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10075", "B45", "NO.2 DG CYL.6 EXH. GAS TEMP. SENSOR FAIL")
                    ]
                    
                    # Write analog data with descriptions and timestamps
                    for channel, var_name, description, unit in analog_channels:
                        value = self.dg2_data.get(var_name, 0)
                        log.write(f"{self.imo_no},{self.dg2_serial},{channel},{description},{timestamp_str},{value},{unit}\n")
                    
                    # Write digital data with descriptions and timestamps
                    for channel, var_name, description in digital_channels:
                        value = self.dg2_data.get(var_name, 0)
                        log.write(f"{self.imo_no},{self.dg2_serial},{channel},{description},{timestamp_str},{value},ON/OFF\n")
                        
        except Exception as e:
            self.logger.error(f"Error writing DG2 CSV: {e}")

    def write_dg3_csv(self):
        """Write DG3 data to CSV with thread safety, channel descriptions and timestamps"""
        dt = datetime.datetime.now()
        timestamp_str = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        logfile = f'/home/drums/csv/MOD_NDY1274_DG_3-{dt.year}-{dt.month}-{dt.day}-{dt.hour}-{dt.minute}.csv'
        
        try:
            with self.data_lock:
                with open(logfile, "a") as log:
                    # Channel mappings with descriptions for DG3
                    analog_channels = [
                        ("30003", "J1", "NO.3 DG L.O. ENGINE INLET HIGH TEMP. ALA", "deg C"),
                        ("30004", "J2", "NO.3 DG C.F.W. ENG. OUTLET HIGH TEMP ALA", "deg C"),
                        ("30006", "J3", "NO.3 DG CYL1 EXH. GAS TEMP.", "deg C"),
                        ("30007", "J4", "NO.3 DG CYL2 EXH. GAS TEMP.", "deg C"),
                        ("30008", "J5", "NO.3 DG CYL3 EXH. GAS TEMP.", "deg C"),
                        ("30009", "J6", "NO.3 DG CYL4 EXH. GAS TEMP.", "deg C"),
                        ("30010", "J7", "NO.3 DG CYL5 EXH. GAS TEMP.", "deg C"),
                        ("30011", "J8", "NO.3 DG CYL6 EXH. GAS TEMP.", "deg C"),
                        ("30014", "J9", "NO.3 DG EXH. GAS T/C INLET 1 TEMP", "deg C"),
                        ("30015", "J10", "NO.3 DG EXH. GAS T/C INLET 2 TEMP H", "deg C"),
                        ("30016", "J11", "NO.3 DG EXH. GAS TEMP. T/C OUTLET", "deg C"),
                        ("30017", "J12", "NO.3 DG C.F.W. ENG. INLET LOW PRESS. ALA", "MPa"),
                        ("30018", "J13", "NO.3 DG BOOST AIR PRESS.", "MPa"),
                        ("30020", "J14", "NO.3 DG START AIR LOW PRESS. ALARM", "MPa"),
                        ("30021", "J15", "NO.3 DG F.O. PRESS. INLET", "MPa"),
                        ("30025", "J16", "NO.3 DG LUB OIL LOW PRESS ALARM", "MPa"),
                        ("30026", "J17", "NO.3 DG ENGINE SPEED", "min-1"),
                        ("30028", "J18", "NO.3 DG ENGINE LOAD", "kW"),
                        ("30029", "J19", "NO.3 DG ENGINE RUNNING HOUR", "10xHour")
                    ]
                    
                    digital_channels = [
                        ("10001", "A1", "NO.3 DG LO ENG INLET FILTER DIFF. PRE. H"),
                        ("10002", "A2", "NO.3 DG CONTROL AIR LOW PRESS. ALARM"),
                        ("10009", "A3", "NO.3 DG T/C LO. LOW PRESS. ALARM"),
                        ("10012", "A6", "NO.3 DG F.O. LEAKED AND LEVEL HIGH ALARM"),
                        ("10013", "A7", "NO.3 DG L.O. SUMP TANK LEVEL LOW ALARM"),
                        ("10017", "A8", "NO.3 DG ENGINE RUNNING"),
                        ("10018", "A9", "NO.3 DG READY TO START"),
                        ("10019", "A10", "NO.3 DG OVER SPEED (STOP)"),
                        ("10020", "A11", "NO.3 DG CFW. ENG. OUTLET HIGH TEMP. STOP"),
                        ("10021", "A12", "NO.3 DG L.O. INLET LOW PRESS. LOW STOP"),
                        ("10023", "A13", "NO.3 DG EMERGENCY STOP(REMOTE/LOCAL)"),
                        ("10024", "A14", "NO.3 DG START FAILURE"),
                        ("10025", "A15", "NO.3 DG PRE. LO. PUMP MOTOR FAILURE (Thermal)"),
                        ("10026", "A16", "NO.3 DG PRIMING LUB OIL PRESS. LOW ALARM"),
                        ("10027", "A17", "NO.3 DG PRE. LO. PUMP RUNNING"),
                        ("10033", "A18", "NO.3 DG SYSTEM FAILURE"),
                        ("10034", "A19", "NO.3 DG CONTROL MODULE FAILURE"),
                        ("10035", "A20", "NO.3 DG SAFETY MODULE FAILURE"),
                        ("10036", "A21", "NO.3 DG LINK TO ENGINE COND DISPLAY FAIL"),
                        ("10037", "A22", "NO.3 DG LINK TO REMOTE I/O-1 FAILURE"),
                        ("10059", "A23", "NO.3 DG EM'CY STOP SWITCH OF EXTERNAL"),
                        ("10060", "A24", "NO.3 DG EM'CY STOP SWITCH OF ECD"),
                        ("10061", "A25", "NO.3 DG HIGH TEMP C.W. TEMP. SWITCH FAIL"),
                        ("10062", "A26", "NO.3 DG LUB.OIL PRESS. SWITCH FAILURE"),
                        ("10064", "A27", "NO.3 DG EM'CY STOP SOLENOID VALVE  FAIL"),
                        ("10067", "A28", "NO.3 DG L.O. ENGINE IN TEMP SENSOR FAIL"),
                        ("10068", "A29", "NO.3 DG H.T. C. W. OUT. TEMP SENSOR FAIL"),
                        ("10078", "A30", "NO.3 DG EXH GAS TC IN 1 TEMP SENSOR FAIL"),
                        ("10079", "A31", "NO.3 DG EXH GAS TC IN 2 TEMP SENSOR FAIL"),
                        ("10080", "A32", "NO.3 DG EXH. GAS TC OUT TEMP SENSOR FAIL"),
                        ("10081", "A33", "NO.3 DG H.T. C.W. PRESS IN SENSOR FAIL"),
                        ("10082", "A34", "NO.3 DG BOOST AIR PRESS. SENSOR FAIL"),
                        ("10084", "A35", "NO.3 DG STARTING AIR PRESS. SENSOR FAIL"),
                        ("10085", "A36", "NO.3 DG F.O. INLET PRESS SENSOR FAIL"),
                        ("10089", "A37", "NO.3 DG L.O. IN. PRESS. SENSOR FAIL"),
                        ("10090", "A38", "NO.3 DG ALL SPEED PICKUP SENSOR FAILURE"),
                        ("10091", "A39", "NO.3 DG LOAD INPUT FAILURE "),
                        ("10070", "A40", "NO.3 DG CYL.1 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10071", "A41", "NO.3 DG CYL.2 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10072", "A42", "NO.3 DG CYL.3 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10073", "A43", "NO.3 DG CYL.4 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10074", "A44", "NO.3 DG CYL.5 EXH. GAS TEMP. SENSOR FAIL"),
                        ("10075", "A45", "NO.3 DG CYL.6 EXH. GAS TEMP. SENSOR FAIL")
                    ]
                    
                    # Write analog data with descriptions and timestamps
                    for channel, var_name, description, unit in analog_channels:
                        value = self.dg3_data.get(var_name, 0)
                        log.write(f"{self.imo_no},{self.dg3_serial},{channel},{description},{timestamp_str},{value},{unit}\n")
                    
                    # Write digital data with descriptions and timestamps
                    for channel, var_name, description in digital_channels:
                        value = self.dg3_data.get(var_name, 0)
                        log.write(f"{self.imo_no},{self.dg3_serial},{channel},{description},{timestamp_str},{value},ON/OFF\n")
                        
        except Exception as e:
            self.logger.error(f"Error writing DG3 CSV: {e}")

    def write_all_csv_files(self):
        """Write all CSV files with synchronized data"""
        try:
            self.write_dg1_csv()
            self.write_dg2_csv()
            self.write_dg3_csv()
            self.logger.info("All CSV files written successfully")
        except Exception as e:
            self.logger.error(f"Error writing CSV files: {e}")

    def get_status_report(self):
        """Generate status report for monitoring"""
        return {
            'collection_count': self.collection_count,
            'error_count': self.error_count,
            'last_collection': self.last_collection_time.isoformat() if self.last_collection_time else None,
            'collection_in_progress': self.collection_in_progress,
            'connection_success_rate': ((self.collection_count / max(self.collection_count + self.error_count, 1)) * 100)
        }

# Threading functions for schedule compatibility
def run_threaded(job_func):
    """Run job function in a separate thread"""
    job_thread = threading.Thread(target=job_func)
    job_thread.daemon = True
    job_thread.start()

# Global collector instance
collector = EnhancedDataCollector()

def collect_and_log_data():
    """Main scheduled function that collects data and writes CSV files"""
    try:
        start_time = datetime.datetime.now()
        
        # Collect all data first
        success = collector.collect_all_data()
        
        # Always write CSV files (with last good data if collection failed)
        collector.write_all_csv_files()
        
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        status = "SUCCESS" if success else "PARTIAL"
        collector.logger.info(f"Collection cycle completed in {duration:.2f}s - Status: {status}")
        
        # Log status every 10 cycles
        if collector.collection_count % 10 == 0:
            status_report = collector.get_status_report()
            collector.logger.info(f"Status Report: {status_report}")
            
    except Exception as e:
        collector.logger.error(f"Critical error in collection cycle: {e}")

# Main execution
if __name__ == "__main__":
    try:
        collector.logger.info("Enhanced Data Collector v2.0 starting up...")
        collector.logger.info(f"Modbus target: {collector.modbus_host}:{collector.modbus_port}")
        
        # Schedule data collection every minute
        schedule.every(1).minutes.do(run_threaded, collect_and_log_data)
        
        collector.logger.info("Scheduler configured for 1-minute intervals")
        collector.logger.info("Data collector is running. Press Ctrl+C to stop.")
        
        # Main execution loop
        while True:
            try:
                schedule.run_pending()
                sleep(1)  # Check every second instead of 0.1 for better performance
                
            except KeyboardInterrupt:
                collector.logger.info("Shutdown requested by user")
                break
                
            except Exception as e:
                collector.logger.error(f"Unexpected error in main loop: {e}")
                sleep(5)  # Wait before continuing after error
                
    except Exception as e:
        print(f"FATAL ERROR: Failed to start data collector: {e}")
    
    finally:
        collector.logger.info("Enhanced Data Collector v2.0 shutdown complete")
        print("Data collector stopped.")