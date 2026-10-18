#!/usr/bin/python3
'''
Created By: Romel
Version: 1.5
Date: 21.09.2023
This script is used to encrypt the zip files on /home/drums/zip/ directory.
'''
import os
import subprocess
import shutil
import time

ZIP_DIR = '/home/drums/zip/'
ASC_DIR = '/home/drums/asc/'
ARCHIVE_DIR = '/home/drums/archive/'

def encrypt_zip_files():
    # Check if the ZIP and ASC directories exist to avoid errors, create if not
    if not os.path.exists(ZIP_DIR):
        print(f"The directory {ZIP_DIR} does not exist.")
        return

    if not os.path.exists(ASC_DIR):
        os.makedirs(ASC_DIR)

    if not os.path.exists(ARCHIVE_DIR):
        os.makedirs(ARCHIVE_DIR)

    # List all zip files in the directory
    zip_files = [f for f in os.listdir(ZIP_DIR) if f.endswith('.zip')]

    for zip_file in zip_files:
        zip_path = os.path.join(ZIP_DIR, zip_file)
        # Skip empty files
        if os.path.getsize(zip_path) == 0:
            continue

        asc_file = zip_file + '.asc'
        asc_path = os.path.join(ASC_DIR, asc_file)

        # GPG command to encrypt the zip file with automatic overwrite
        gpg_command = ['gpg', '--encrypt', '--trust-model', 'always', '--sign', '--armor', '--yes', '-r', 'romel@daikai.com', '-o', asc_path, zip_path]

        try:
            subprocess.run(gpg_command, check=True)
            print(f"Encrypted: {zip_file} to {asc_file}")
            # Move the successfully encrypted zip file to the archive directory
            shutil.move(zip_path, os.path.join(ARCHIVE_DIR, zip_file))
            print(f"Moved {zip_file} to {ARCHIVE_DIR}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to encrypt {zip_file}: {e}. Deleting the zip file.")
            try:
                os.remove(zip_path)  # Attempt to delete the problematic zip file
                print(f"Deleted {zip_file} due to encryption failure.")
            except Exception as delete_error:
                print(f"Failed to delete {zip_file}: {delete_error}")

if __name__ == '__main__':
    while True:
        encrypt_zip_files()
        time.sleep(180)  # Wait for 3 minutes before next check



