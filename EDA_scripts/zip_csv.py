#!/usr/bin/python3
'''
Created By: Romel
Version: 2.20
Date: 19.09.2023
This script is used to zip all the csv files on /home/drums/csv/ directory.
'''
import os
import zipfile
from datetime import datetime
import time

# Define the directory to check for CSV files and the directory to save zip files
csv_dir = '/home/drums/csv/'
zip_dir = '/home/drums/zip/'

# Ensure the zip directory exists
os.makedirs(zip_dir, exist_ok=True)

# Function to zip non-empty CSV files and delete the files after zipping
def zip_and_delete_csv_files():
    # Generate the timestamp
    timestamp = datetime.now().strftime("%m-%d-%Y-%H-%M-%S")
    # Define the full path for the zip file
    zip_filename = os.path.join(zip_dir, f'EDA_NK-{timestamp}.zip')

    # Find all CSV files in the csv_dir
    csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]

    # Initialize variable to check if at least one file was added to the zip
    files_added_to_zip = False

    # If there are CSV files, check each file's size and process accordingly
    if csv_files:
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            for file in csv_files:
                file_path = os.path.join(csv_dir, file)
                # Check if the file size is greater than 0
                if os.path.getsize(file_path) > 0:
                    try:
                        # Write each non-empty CSV file to the zip file
                        zipf.write(file_path, arcname=file)
                        files_added_to_zip = True
                        print(f'Added {file} to {zip_filename}')
                        # Delete the file after adding it to the zip to avoid any system limit issues
                        os.remove(file_path)
                        print(f'Deleted {file} after zipping')
                    except Exception as e:
                        print(f"Error processing {file}: {e}")
                else:
                    # If the file is empty, delete it
                    try:
                        os.remove(file_path)
                        print(f'Deleted empty file: {file}')
                    except Exception as e:
                        print(f"Error deleting {file}: {e}")

        if files_added_to_zip:
            print(f'Created zip file: {zip_filename}')
        else:
            # If no files were added to the zip, delete the empty zip file
            os.remove(zip_filename)
            print('No non-empty CSV files found. No zip file created.')
    else:
        print('No CSV files found. Doing nothing.')

# Main loop to check every 3 minutes
while True:
    zip_and_delete_csv_files()
    # Wait for 180 seconds (3 minutes) before the next check
    time.sleep(180)
